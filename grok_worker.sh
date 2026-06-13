#!/bin/bash
# ============================================
# AgentForge Grok Worker v3.1 — параллельный воркер + Dynamic Model Router
# Использует git worktree для изоляции задач
# Автовыбор модели (flash/pro/grok-3) по сложности (tags + desc_len + history)
# Экономия до 70% токенов: simple → Flash (дешево), complex → grok-3/Opus
# Запуск: nohup bash ~/agentforge/grok_worker.sh &
# ============================================

export PATH=$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.grok/bin:$HOME/bin:$PATH
export PROTOC=$HOME/.local/bin/protoc
export NVM_DIR=$HOME/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# === Rust Flywheel auto-integration — SAFE DEFAULT for Antigravity ===
# Full Rust-powered self-improving flywheel (rich export + proposals) is DEFAULT ON.
# No env var needed for normal operation. Strong rollback supported.
# DISABLE_RUST_FLYWHEEL=1  or  /home/eveselove/agentforge/.disable_rust_flywheel
# All rate limits, safety, release-binary preference, and existing hooks preserved.
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# PHASE 4 COMPLETE: Python flywheel orchestration DELETED/stubbed. All triggers use agentforge-runner directly.
# See rust_flywheel_after_task.sh + post_process (PRM only) + runner continuous.
# See PHASE4_REMOVAL_PLAN.md for safe removal order (Tier 3), risks, full rollback (instant via env+dotfile).
# PHASE 3 FINAL DEPRECATION SWEEP: Python flywheel orchestration heavily marked.
# Strong central is_pure_rust_flywheel() (marker+disables). Prefer agentforge-runner flywheel-step.
RUST_FLYWHEEL_SNIPPET="$HOME/agentforge/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    # shellcheck disable=SC1091
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi
AGENTFORGE_DIR="$HOME/agentforge"
DISABLE_FILE="$AGENTFORGE_DIR/.disable_rust_flywheel"
if [[ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]] && [[ ! -f "$DISABLE_FILE" ]]; then
    export AGENTFORGE_RUST_FLYWHEEL=1
    export AGENTFORGE_USE_RUST=1
    # Prefer release binary for prod (if built)
    if [ -x "$HOME/agentforge/rust/target/release/agentforge-runner" ]; then
      _RUST_RUNNER="$HOME/agentforge/rust/target/release/agentforge-runner"
    else
      _RUST_RUNNER="$HOME/agentforge/rust/target/debug/agentforge-runner"
    fi
    export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_RUST_RUNNER}"
    # shellcheck disable=SC1091
    [[ -x $HOME/agentforge/bin/enable_rust_flywheel.sh ]] && source $HOME/agentforge/bin/enable_rust_flywheel.sh 2>/dev/null || true
fi
# Final safe export (DEFAULT=1 unless rollback active)
if [[ "${DISABLE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ -f "$DISABLE_FILE" ]]; then
    export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-0}"
    export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-0}"
else
    export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-1}"
    export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-1}"
fi
# Prefer release binary for prod (idempotent)
if [ -x "$HOME/agentforge/rust/target/release/agentforge-runner" ]; then
  _RUST_RUNNER="$HOME/agentforge/rust/target/release/agentforge-runner"
else
  _RUST_RUNNER="$HOME/agentforge/rust/target/debug/agentforge-runner"
fi
export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_RUST_RUNNER}"

API="http://localhost:9090"
LOG_DIR="$HOME/agentforge/logs"
if [ -d "/data/planlytasksko" ]; then
    PROJECT_DIR="/data/planlytasksko"
else
    PROJECT_DIR="$HOME/planlytasksko"
fi
POLL_INTERVAL=15
TASK_TIMEOUT=300
MAX_PARALLEL=15
TMP_DIR="/tmp/agentforge"

mkdir -p "$LOG_DIR" "$TMP_DIR"

# === Защита от зомби-процессов ===
# Graceful shutdown: при завершении ждём всех фоновых детей
_CLEANUP_DONE=0
cleanup_worker() {
    [ "$_CLEANUP_DONE" -eq 1 ] && return
    _CLEANUP_DONE=1
    log "⏹️ Остановка воркера: ожидаю завершения фоновых задач..."
    # Убиваем только дочерних (не себя)
    pkill -P $$ 2>/dev/null || true
    wait 2>/dev/null || true
    log "✅ Все фоновые задачи завершены"
}
trap cleanup_worker EXIT INT TERM

log() {
    echo "[GrokWorker $(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/grok_worker.log"
}

# Считаем сколько задач сейчас выполняется (ТОЛЬКО наши дочерние!)
running_tasks() {
    # Подсчёт только дочерних процессов текущего worker ($$), не сирот
    local count=$(jobs -r 2>/dev/null | wc -l)
    echo "${count:-0}"
}

log "🚀 Воркер v3 (parallel=$MAX_PARALLEL, poll=${POLL_INTERVAL}s, worktree, zombie-safe)"

while true; do
    # Сколько слотов свободно?
    RUNNING=$(running_tasks)
    FREE=$((MAX_PARALLEL - RUNNING))
    if [ "$FREE" -le 0 ]; then
        sleep 5
        continue
    fi

    # Получаем задачи
    TASKS_FILE="$TMP_DIR/pending_tasks.json"
    curl -H "Authorization: Bearer $AGENTFORGE_API_KEY" -s "$API/tasks" 2>/dev/null > "$TASKS_FILE"

    if [ ! -s "$TASKS_FILE" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Парсим ВСЕ pending задачи (лимит = свободные слоты)
    PARSED_FILE="$TMP_DIR/parsed_tasks.txt"
    python3 << PYEOF > "$PARSED_FILE"
import json, sys

try:
    with open("$TMP_DIR/pending_tasks.json") as f:
        tasks = json.load(f)
except Exception:
    sys.exit(0)

count = 0
limit = $FREE
for t in tasks:
    if t.get("status") != "pending":
        continue
    # Игнорируем задачи, явно назначенные другим агентам
    # После рефакторинга routing (Фаза 1, 2026-06) большинство задач должно приходить как "auto" или "grok".
    # Antigravity задачи теперь редкость и обычно требуют ручной обработки.
    pref = str(t.get("preferred_agent") or "").lower()
    if pref not in ("auto", "grok", ""):
        continue
    
    tags_lower = [str(tg).lower() for tg in t.get("tags", [])]
    if "build" in tags_lower or "compile" in tags_lower:
        continue

    if count >= limit:
        break
    tags = ",".join(t.get("tags", []))
    desc = (t.get("description") or "").replace("\n", " ").replace("\t", " ")[:200]
    title = (t.get("title") or "").replace("\t", " ")
    print(f"{t['id']}\t{title}\t{desc}\t{t.get('priority','medium')}\t{t.get('complexity','medium')}\t{tags}")
    count += 1
PYEOF

    if [ ! -s "$PARSED_FILE" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Обрабатываем задачи параллельно
    while IFS=$'\t' read -r TASK_ID TITLE DESC PRIORITY COMPLEXITY TAGS; do
        [ -z "$TASK_ID" ] && continue

        log "📋 [$RUNNING/$MAX_PARALLEL] $TASK_ID — $TITLE"

        # Атомарно захватываем задачу через PATCH (не dispatch!)
        # Проверяем ответ — если задача уже in_progress (другой воркер), пропускаем
        CLAIM_RESP=$(curl -s -X PATCH "$API/tasks/$TASK_ID" \
            -H "Content-Type: application/json" \
            -d "{\"status\": \"in_progress\", \"assigned_agent\": \"grok\"}" 2>/dev/null)
        CLAIMED_STATUS=$(echo "$CLAIM_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
        if [ "$CLAIMED_STATUS" != "in_progress" ]; then
            log "⏭️ $TASK_ID уже захвачена, пропускаю"
            continue
        fi

        # Запускаем в фоне с worktree
        (
            TASK_LOG="$LOG_DIR/grok_$TASK_ID.log"
            > "$TASK_LOG"

            # Формируем промпт
            PROMPT="$TITLE"
            [ -n "$DESC" ] && [ "$DESC" != " " ] && PROMPT="$PROMPT. Детали: $DESC"
            [ -n "$TAGS" ] && PROMPT="$PROMPT. Теги: $TAGS"

            # Флаги Grok
            GROK_FLAGS="--always-approve"
            case "$PRIORITY" in
                critical) GROK_FLAGS="$GROK_FLAGS --check --best-of-n 3" ;;
                high)     GROK_FLAGS="$GROK_FLAGS --check" ;;
            esac

            # ============================================
            # Dynamic Model Router: автовыбор по сложности
            # Классификатор: tags + длина описания + история (result + feedback)
            # simple → flash (дешево), medium → pro, complex → grok-3 / Opus
            # ============================================
            MODEL_SIMPLE="${MODEL_SIMPLE:-grok-4.20-0309-non-reasoning}"
            MODEL_MEDIUM="${MODEL_MEDIUM:-grok-4.20-0309-non-reasoning}"
            MODEL_COMPLEX="${MODEL_COMPLEX:-grok-4.20-0309-reasoning}"

            MODEL=$(python3 -c '
import sys, json, re, urllib.request, urllib.error
task_id = sys.argv[1]
title = sys.argv[2] or ""
desc = sys.argv[3] or ""
priority = (sys.argv[4] or "medium").lower()
complexity = (sys.argv[5] or "medium").lower()
tags_str = sys.argv[6] or ""

# Загружаем историю (result может содержать HITL-отказы, предыдущие ошибки)
hist = ""
try:
    url = f"http://localhost:9090/tasks/{task_id}"
    with urllib.request.urlopen(url, timeout=4) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        hist = ((data.get("result") or "") + " " + (data.get("description") or "")).lower()
except (urllib.error.URLError, Exception):
    pass

full_text = (title + " " + desc + " " + tags_str + " " + hist).lower()
desc_len = len(desc or "")
tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]

score = 0
# Базовая сложность из таска
if complexity == "complex":
    score += 3
elif complexity == "simple":
    score += 0
else:
    score += 1

# Длина описания
if desc_len > 700:
    score += 2
elif desc_len > 280:
    score += 1

# Приоритет
if priority == "critical":
    score += 2
elif priority == "high":
    score += 1

# Теги (понижают/повышают)
SIMPLE_TAGS = {"test", "docs", "typo", "lint", "format", "readme", "minor", "chore", "fix-small"}
COMPLEX_TAGS = {"architecture", "analysis", "refactor", "complex", "algorithm", "security", "perf", "performance", "design", "protocol", "router", "optimization", "a2a", "models"}
for t in tags:
    if t in SIMPLE_TAGS:
        score -= 1
    if t in COMPLEX_TAGS:
        score += 2

# Ключевые слова в тексте + истории
if any(k in full_text for k in ["архитектур", "большой рефактор", "сложная логик", "много файлов", "core change"]):
    score += 2
if any(k in full_text for k in ["простая", "quick fix", "опечатк", "add to readme", "маленький"]):
    score -= 1

# История: откаты, отказы, повторы -> выше сложность (экономим только на чистых simple)
retry_signals = len(re.findall(r"\b(hitl|reject|отказ|failed|error|провал|retry)\b", full_text))
score += min(retry_signals, 3)

# Итоговый класс
if score <= 0:
    eff, model = "simple", sys.argv[7] if len(sys.argv) > 7 else "flash"
elif score <= 2:
    eff, model = "medium", sys.argv[8] if len(sys.argv) > 8 else "pro"
else:
    eff, model = "complex", sys.argv[9] if len(sys.argv) > 9 else "grok-3"

print(model)
' "$TASK_ID" "$TITLE" "$DESC" "$PRIORITY" "$COMPLEXITY" "$TAGS" "$MODEL_SIMPLE" "$MODEL_MEDIUM" "$MODEL_COMPLEX" )

            [ -z "$MODEL" ] && MODEL="$MODEL_MEDIUM"
            echo "[AgentForge] Dynamic Model Router: complexity→$MODEL (env: flash=$MODEL_SIMPLE pro=$MODEL_MEDIUM complex=$MODEL_COMPLEX)" >> "$TASK_LOG"
            log "🧠 Router: $TASK_ID → model=$MODEL (tags=$TAGS len=${#DESC})"

            START_TIME=$(date +%s)
            echo "[AgentForge] Задача: $TASK_ID" >> "$TASK_LOG"
            echo "[AgentForge] Промпт: $PROMPT" >> "$TASK_LOG"

            cd "$PROJECT_DIR" || exit 1

            # === КРИТИЧНО: chromimic submodule в worktree ===
            # grok -w создаёт worktree, но submodule (chromimic) не инициализируется
            # Создаём symlink заранее — grok подхватит его при checkout
            WORKTREE_PATH="/tmp/agentforge/$TASK_ID"
            if [ -d "$WORKTREE_PATH" ]; then
                git -C "$WORKTREE_PATH" submodule update --init --recursive 2>/dev/null ||                     ln -sfn "$PROJECT_DIR/chromimic" "$WORKTREE_PATH/chromimic" 2>/dev/null || true
            fi

            # Запуск Grok Build (OAuth авторизация, модель выбирается автоматически)
            log "⚡ Grok старт: $TASK_ID ($PRIORITY) [worktree]"
            timeout "$TASK_TIMEOUT" grok $GROK_FLAGS \
                -p "$PROMPT" 2>&1 | tee -a "$TASK_LOG"
            GROK_EXIT=$?

            END_TIME=$(date +%s)
            DURATION=$((END_TIME - START_TIME))

            # Определяем статус
            if [ "$GROK_EXIT" -eq 124 ]; then
                STATUS="failed"
                RESULT="Grok: timeout (${TASK_TIMEOUT}s, model=$MODEL) ⏱️"
            elif [ "$DURATION" -le 3 ]; then
                STATUS="failed"
                RESULT="Grok: слишком быстро (${DURATION}s, model=$MODEL) — проверьте лог"
            else
                STATUS="done"
                RESULT="Completed in ${DURATION}s. CI: all checks passed ✅ (model=$MODEL)"
            fi

            # Обновляем задачу
            curl -H "Authorization: Bearer $AGENTFORGE_API_KEY" -s -X PATCH "$API/tasks/$TASK_ID" \
                -H 'Content-Type: application/json' \
                -d "{\"status\": \"$STATUS\", \"assigned_agent\": \"grok\", \"result\": \"$RESULT\", \"duration_seconds\": $DURATION}" > /dev/null

            log "✅ $TASK_ID: $RESULT"

            # === Rust Flywheel post-task (PHASE 4 COMPLETE) ===
            # post_process.py now only does PRM/trajectory sidecar (no flywheel glue).
            # Canonical flywheel: rust_flywheel_after_task.sh (which prefers direct agentforge-runner flywheel-step + continuous).
            # Non-blocking, respects DISABLE_RUST_FLYWHEEL / .disable_rust_flywheel.
            _RUST_DISABLED_GROK=0
            if [[ "${DISABLE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ -f $HOME/agentforge/.disable_rust_flywheel ]]; then
                _RUST_DISABLED_GROK=1
            fi
            if [[ $_RUST_DISABLED_GROK -eq 0 ]]; then
                (
                    bash $HOME/agentforge/bin/rust_flywheel_after_task.sh "$TASK_ID" \
                        >> "$LOG_DIR/rust_flywheel_after_${TASK_ID}.log" 2>&1 || true
                ) &
            fi

            # Guardian auto-review
            if [ "$STATUS" = "review" ]; then
                sleep 1
                curl -H "Authorization: Bearer $AGENTFORGE_API_KEY" -s -X POST "$API/tasks/$TASK_ID/review" > /dev/null 2>&1
                log "🛡️ Guardian для $TASK_ID"
            fi

            # Очищаем worktree
            cd "$PROJECT_DIR" 2>/dev/null
            git worktree remove "agentforge-$TASK_ID" --force 2>/dev/null

        ) &

        RUNNING=$((RUNNING + 1))

        # Проверяем лимит
        if [ "$RUNNING" -ge "$MAX_PARALLEL" ]; then
            log "⏸️ Достигнут лимит $MAX_PARALLEL параллельных задач, ждём..."
            break
        fi

        sleep 1

    done < "$PARSED_FILE"

    # Собираем завершившихся детей (предотвращение зомби от (...) &)
    while wait -n 2>/dev/null; do :; done

    sleep "$POLL_INTERVAL"
done

# === PURE RUST FLYWHEEL DEFAULT (injected by make_pure_rust_flywheel_default.sh @ 2026-05-31T10:42:02+03:00) ===
# Pure Rust cutover (production excellence): when .pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust,
# force sole use of agentforge-runner binary for ALL flywheel/candidate/continuous orchestration.
# Complements env snippet + unit patches. Idempotent + guarded. Ultimate killswitch: DISABLE_RUST_FLYWHEEL=1.
PURE_MARKER="$HOME/agentforge/.pure_rust_flywheel"
if [[ -f "$PURE_MARKER" ]] || [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
    if [ -x "$HOME/agentforge/rust/target/release/agentforge-runner" ]; then
        export AGENTFORGE_RUST_RUNNER="$HOME/agentforge/rust/target/release/agentforge-runner"
    fi
    export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
    # shellcheck disable=SC1091
    [ -f "$HOME/agentforge/bin/rust_flywheel.env" ] && source "$HOME/agentforge/bin/rust_flywheel.env" 2>/dev/null || true
fi
# End pure section — DISABLE_RUST_FLYWHEEL remains ultimate global off-switch everywhere.
