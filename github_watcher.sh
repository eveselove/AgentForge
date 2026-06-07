#!/bin/bash
# github_watcher.sh — Auto-Discovery: задачи из GitHub Issues
#
# Purpose:
#   Каждые 5 минут (cron) через `gh api` находит открытые issues с label 'agentforge'.
#   Для каждого *нового* (не seen ранее) создаёт задачу в AgentForge
#   через POST /tasks с тегами ["github", "automation", "discovery"].
#   Использует state-файл чтобы не дублировать задачи.
#
# Integration:
#   - Работает с task_queue.py (FastAPI :8080)
#   - Похож по стилю на watchdog.sh (inline python + bash logging)
#   - Создаваемые задачи сразу попадают в dispatcher / resolve_agent
#
# Usage (manual):
#   GH_REPO=owner/repo ./github_watcher.sh
#
# Crontab (автоматически добавляется скриптом установки):
#   */5 * * * * bash /home/eveselove/agentforge/github_watcher.sh >> /home/eveselove/agentforge/logs/github_watcher.log 2>&1
#
# Config (env):
#   GH_REPO     — репозиторий для мониторинга (по умолчанию agx/planlytasksko)
#   API         — база API (по умолчанию http://localhost:8080)
#
# Tags: github,automation,discovery

set -euo pipefail

API="${API:-http://localhost:8080}"
LOG_DIR="/home/eveselove/agentforge/logs"
DATA_DIR="/home/eveselove/agentforge/data"
SEEN_FILE="$DATA_DIR/seen_agentforge_issues.txt"

# Определяем репозиторий (можно переопределить GH_REPO=... в cron или окружении)
GH_REPO="${GH_REPO:-}"
if [[ -z "$GH_REPO" ]]; then
  # Пытаемся автоопределить через gh (если cwd — git-репо с remote)
  GH_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)
fi
if [[ -z "$GH_REPO" ]]; then
  GH_REPO="eveselove/planlytasksko"
fi

mkdir -p "$LOG_DIR" "$DATA_DIR"
touch "$SEEN_FILE"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/github_watcher.log" >&2
}

log "=== github_watcher START (repo=${GH_REPO}) ==="

if ! command -v gh >/dev/null 2>&1; then
  log "ERROR: gh CLI не найден. Установи GitHub CLI и выполни gh auth login"
  exit 1
fi

# Получаем открытые issues с лейблом agentforge (до 50 последних)
# gh api возвращает JSON; фильтруем только нужные поля
issues_json=$(gh api \
  "repos/${GH_REPO}/issues?labels=agentforge&state=open&per_page=50&sort=created&direction=desc" \
  --jq '[.[] | {number, title, body, html_url, created_at, user: .user.login}]' 2>/dev/null || echo '[]')

count=$(echo "$issues_json" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)

if [[ "$count" -eq 0 ]]; then
  log "Нет открытых issues с label 'agentforge' в ${GH_REPO}"
  log "=== github_watcher END (nothing to do) ==="
  exit 0
fi

log "Найдено $count открытых agentforge issues. Проверяем новые..."

# Основная логика на Python (удобно работать с JSON + HTTP + state)
echo "$issues_json" | python3 -c '
import sys, json, urllib.request, os, time

API = "'"$API"'"
SEEN_FILE = "'"$SEEN_FILE"'"
GH_REPO = "'"$GH_REPO"'"

# Загружаем seen (один ключ на строку: owner/repo#123)
seen = set()
try:
  with open(SEEN_FILE, "r", encoding="utf-8") as f:
    for line in f:
      line = line.strip()
      if line:
        seen.add(line)
except FileNotFoundError:
  pass

issues = json.load(sys.stdin)
created_count = 0
errors = []

for issue in issues:
  num = int(issue.get("number", 0))
  if not num:
    continue
  key = f"{GH_REPO}#{num}"
  if key in seen:
    continue

  title = (issue.get("title") or f"GitHub Issue #{num}").strip()[:200]
  body = (issue.get("body") or "").strip()
  url = issue.get("html_url") or f"https://github.com/{GH_REPO}/issues/{num}"
  user = issue.get("user") or "unknown"
  created_at = issue.get("created_at") or ""

  description = f"""{body}

---
**Источник:** {url}
**Автор:** @{user}
**Создано в GitHub:** {created_at}

Авто-дискавери через github_watcher.sh (label=agentforge)
"""

  payload = {
    "title": title,
    "description": description,
    "priority": "medium",
    "complexity": "medium",
    "preferred_agent": "auto",
    "tags": ["github", "automation", "discovery"]
  }

  data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
  try:
    req = urllib.request.Request(
      f"{API}/tasks",
      data=data,
      headers={"Content-Type": "application/json"},
      method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
      status = resp.status
      if status in (200, 201):
        with open(SEEN_FILE, "a", encoding="utf-8") as sf:
          sf.write(key + "\n")
        print(f"CREATED|{key}|{title}")
        created_count += 1
      else:
        body_err = resp.read().decode("utf-8", errors="replace")[:200]
        print(f"FAIL_HTTP|{key}|HTTP {status}: {body_err}")
        errors.append(key)
  except Exception as e:
    print(f"FAIL|{key}|{str(e)[:120]}")
    errors.append(key)

# Выводим итог для парсинга в bash
print(f"SUMMARY|created={created_count}|errors={len(errors)}|total_seen={len(seen)+created_count}")
' | while IFS='|' read -r ACTION REST; do
  case "$ACTION" in
    CREATED)
      IFS='|' read -r key title <<< "$REST"
      log "✅ Создана задача из ${key}: ${title}"
      ;;
    FAIL*)
      log "❌ Ошибка создания ${REST}"
      ;;
    SUMMARY)
      log "ИТОГ: ${REST}"
      ;;
    *)
      # игнорируем прочее
      ;;
  esac
done

log "=== github_watcher END ==="
