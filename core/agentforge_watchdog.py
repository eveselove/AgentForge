#!/usr/bin/env python3
"""
AgentForge Watchdog & Guardian Daemon
Мониторит активные задачи и убивает зациклившиеся процессы агентов для экономии токенов (token saving kills).
Также выполняет роль Guardian: воскрешает упавшие задачи с добавлением RAG-контекста (auto-retries with RAG context).

Ключевые компоненты для верификации (по запросу задачи):
- log loop heuristics: analyze_log_for_loops (размер, повторы ошибок, tool calls, общие повторы строк, diversity)
- token saving kills: kill_task_process + mark_task_failed (SIGKILL worktree/grok + перевод failed с пометкой экономии)
- auto-retries with RAG context: guardian_loop (через get_last_checkpoint + search_similar_tasks из task_checkpoints FTS5)
- periodic sweeps: auto_review_stale (каждые 6 POLL_INTERVAL вызывает /review/all чтобы не потерять review-задачи)

Запуск: python -m core.agentforge_watchdog или напрямую.
Интеграция: systemd user agentforge-watchdog.service (хотя может указывать на watchdog.py), grok_runner.sh, task_queue.py.
Порты: 9090 (Rust Gateway, единый порт).
"""

import time
import json
import urllib.request
import urllib.error
import os
import subprocess
from collections import Counter
import sys

# Примечание: 're' удалён — не использовался. При необходимости для сложных паттернов циклов можно вернуть.

# Добавляем путь к planlytasksko / agentforge для импорта task_checkpoints (RAG для Guardian)
# Исправлено: более робастный поиск модуля (поддержка core/ и scripts/, разные развёртывания)
for p in [
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),  # agentforge root при запуске из core/
    "/home/eveselove/agentforge",
    "/home/eveselove/planlytasksko",
    os.path.expanduser("~/agentforge"),
    os.path.expanduser("~/planlytasksko"),
    "/data/planlytasksko",
]:
    if os.path.exists(p):
        if p not in sys.path:
            sys.path.insert(0, p)
        # также проверить вложенный core/
        core_p = os.path.join(p, "core")
        if os.path.exists(core_p) and core_p not in sys.path:
            sys.path.insert(0, core_p)

try:
    from task_checkpoints import get_last_checkpoint, search_similar_tasks
except ImportError:
    try:
        from scripts.task_checkpoints import get_last_checkpoint, search_similar_tasks
    except ImportError:
        get_last_checkpoint = None
        search_similar_tasks = None

API_BASE = os.environ.get(
    "AGENTFORGE_API", "http://127.0.0.1:9090"
)  # Gateway (единый порт, 8080 убран)
LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
)
POLL_INTERVAL = 10
LOOP_THRESHOLD = 5  # Если одинаковая строка-ошибка или шаблон появляется >5 раз
MAX_LOG_SIZE_MB = 2.0  # Лимит размера лога (защита от спама)


def log(msg):
    print(f"[Watchdog] {msg}", flush=True)


def api_get(endpoint):
    try:
        req = urllib.request.Request(f"{API_BASE}{endpoint}")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log(f"⚠️ Ошибка API GET {endpoint}: {e}")
        return []


def api_patch(endpoint, payload):
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{API_BASE}{endpoint}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log(f"⚠️ Ошибка API PATCH {endpoint}: {e}")
        return None


def get_active_tasks():
    tasks = api_get("/tasks")
    return [t for t in tasks if t.get("status") in ("dispatched", "in_progress")]


def get_failed_tasks():
    tasks = api_get("/tasks?status=failed")
    return tasks


def kill_task_process(task_id):
    """Найти и убить процесс grok, связанный с задачей (через worktree dir).
    Используется Watchdog'ом для token saving kills: при обнаружении loop
    процесс grok (и worktree) принудительно terminate -9, задача переводится в failed.
    Это экономит токены на бесконечных ретраях/циклах LLM.
    Улучшено: фильтрация пустых pid, логирование количества убитых, fallback pkill.
    """
    worktree_dir = f"agentforge-{task_id}"
    killed_pids = []
    try:
        cmd = ["pgrep", "-f", worktree_dir]
        result = subprocess.run(cmd, capture_output=True, text=True)
        pids = [p for p in result.stdout.strip().split("\n") if p.strip()]

        for pid in pids:
            subprocess.run(["kill", "-9", pid], check=False)
            killed_pids.append(pid)

        cmd2 = ["pgrep", "-f", f"grok_worker.*{task_id}|grok.*{task_id}"]
        res2 = subprocess.run(cmd2, capture_output=True, text=True)
        for pid in [p for p in res2.stdout.strip().split("\n") if p.strip()]:
            subprocess.run(["kill", "-9", pid], check=False)
            killed_pids.append(pid)

        # Fallback: если pgrep не нашёл, но процесс висит по имени grok + task
        if not killed_pids:
            try:
                subprocess.run(["pkill", "-9", "-f", f"grok.*{task_id}"], check=False)
            except Exception:
                pass

        if killed_pids:
            log(f"   [kill] Убиты PID: {killed_pids} для task {task_id}")
        return len(killed_pids) > 0
    except Exception as e:
        log(f"⚠️ Ошибка при убийстве процесса: {e}")
        return False


def mark_task_failed(task_id, reason):
    """Перевести задачу в статус failed с причиной (для Guardian retries и аудита).
    Сообщение специально упоминает 'Сэкономлены токены.' — это и есть цель token saving kills.
    """
    payload = {
        "status": "failed",
        "result": f"[Watchdog] 🛑 Принудительно остановлено: {reason}. Сэкономлены токены.",
    }
    api_patch(f"/tasks/{task_id}", payload)
    log(f"✅ Задача {task_id} помечена как failed.")


def analyze_log_for_loops(log_path):
    """Эвристический анализ лога на бесконечные циклы (log loop heuristics).
    Проверки:
    - Размер лога > MAX_LOG_SIZE_MB (защита от спама токенов)
    - Повторяющиеся строки ошибок/failed/exception >= LOOP_THRESHOLD (5) в последних 50
    - Повторяющиеся вызовы инструментов
    - ОБЩЕЕ зацикливание: любая одинаковая строка повторяется >=5 раз (даже без ключевых слов)
    - Дополнительно: если уникальных строк мало (<5) при большом объёме recent -> подозрение на loop
    Используется для token-saving kills.
    """
    if not os.path.exists(log_path):
        return None

    try:
        size_mb = os.path.getsize(log_path) / (1024 * 1024)
        if size_mb > MAX_LOG_SIZE_MB:
            return f"превышен лимит лога ({size_mb:.1f} MB)"

        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        if not lines:
            return None

        recent_lines = [
            l.strip() for l in lines[-60:] if l.strip()
        ]  # Увеличено до 60 для лучшего покрытия
        if not recent_lines:
            return None

        # 1. Общий счётчик повторов (главная эвристика зацикливания)
        line_counts = Counter(recent_lines)
        most_common_line, most_count = line_counts.most_common(1)[0]
        if most_count >= LOOP_THRESHOLD:
            return f"зацикливание (повтор строки x{most_count}: '{most_common_line[:60]}...')"

        # 2. Специфично ошибки
        error_lines = [
            l
            for l in recent_lines
            if "error" in l.lower() or "failed" in l.lower() or "exception" in l.lower()
        ]
        if error_lines:
            counts = Counter(error_lines)
            most_common, count = counts.most_common(1)[0]
            if count >= LOOP_THRESHOLD:
                return f"зацикливание ошибки ('{most_common[:50]}...')"

        # 3. Зацикливание инструментов (обновлённые паттерны)
        tool_calls = [
            l
            for l in recent_lines
            if any(
                kw in l
                for kw in [
                    "Running tool",
                    "Command output",
                    "tool call",
                    "invoke tool",
                    "execute",
                    "subprocess",
                ]
            )
        ]
        if len(tool_calls) > 15:  # noqa: E501 (slightly softer threshold)
            tcounts = Counter(tool_calls)
            if tcounts and tcounts.most_common(1)[0][1] >= LOOP_THRESHOLD:
                return "зацикливание вызова инструментов"

        # 4. Доп. эвристика: мало разнообразия при длинной истории -> loop (напр. один и тот же "thinking...")
        unique_ratio = len(line_counts) / max(len(recent_lines), 1)
        if len(recent_lines) >= 30 and unique_ratio < 0.2:
            return f"вероятное зацикливание (мало уникальных строк: {len(line_counts)}/{len(recent_lines)})"

        return None
    except Exception as e:
        log(f"⚠️ Ошибка анализа {log_path}: {e}")
        return None


def guardian_loop():
    """Проверяет упавшие задачи и пытается их воскресить с RAG-контекстом.
    Это core часть Guardian Self-Healing.
    - Лимит 3 ретрая (retry_count < 3)
    - Берёт error из result задачи или из последнего чекпоинта (get_last_checkpoint)
    - Выполняет search_similar_tasks (FTS5 RAG из task_checkpoints) по тексту ошибки
    - Добавляет в description секцию --- GUARDIAN RAG CONTEXT --- + AUTO-RETRY note
    - Переводит статус failed -> pending, increment retry_count, чистит result
    - Прямой UPDATE sqlite для description (API не поддерживает PATCH desc)
    - Доп: при воскрешении задач с antigravity -> форсируем grok (политика routing)
    - Защита от дублирования заметок в desc.
    """
    if not get_last_checkpoint:
        log(
            "⚠️ Guardian: get_last_checkpoint недоступен (нет task_checkpoints) — RAG/self-heal ограничен"
        )
        return

    failed_tasks = get_failed_tasks()
    for task in failed_tasks:
        task_id = task["id"]
        retry_count = task.get("retry_count", 0)

        if retry_count < 3:
            log(
                f"🛡️ Guardian: Воскрешение задачи {task_id} (Попытка {retry_count + 1}/3)"
            )

            error_msg = task.get("result", "")

            # Попытаемся достать ошибку из чекпоинтов (лучше, чем из result)
            cp = get_last_checkpoint(task_id)
            if cp and cp.get("data", {}).get("error"):
                error_msg = cp["data"]["error"]

            # RAG поиск похожих прошлых задач (verify: auto-retries with RAG context)
            rag_context = ""
            if search_similar_tasks and error_msg:
                # Ищем похожие задачи по тексту ошибки (первые 200 символов)
                similar = search_similar_tasks(str(error_msg)[:200], limit=3)
                if similar:
                    rag_context = "\n\n--- GUARDIAN RAG CONTEXT ---\nНайдено несколько похожих прошлых задач, которые могут помочь решить эту ошибку:\n"
                    for s in similar:
                        outcome = s.get("outcome", "unknown")
                        title = s.get("title", "untitled")[:60]
                        rag_context += f"- Задача '{title}': Статус: {outcome}. (last_step: {s.get('last_step', '?')})\n"

            new_desc = task.get("description", "")
            guardian_note = f"\n\n--- GUARDIAN AUTO-RETRY ({retry_count + 1}/3) ---\nПредыдущая попытка завершилась ошибкой:\n{error_msg}{rag_context}"

            # Избегаем дублирования логов
            if "--- GUARDIAN AUTO-RETRY" in new_desc:
                new_desc = new_desc.split("--- GUARDIAN AUTO-RETRY")[0].strip()

            new_desc += guardian_note

            # Патчим базу: статус -> pending, обновляем счетчик и описание
            patch_data = {
                "status": "pending",
                "retry_count": retry_count + 1,
                "result": None,  # Clear previous failure result
            }

            # Fair work-stealing: при воскрешении сбрасываем assigned_agent,
            # preferred_agent остаётся — пусть конкурируют за задачу
            patch_data["assigned_agent"] = None

            api_patch(f"/tasks/{task_id}", patch_data)

            # Поскольку API не поддерживает обновление description, мы обновим его напрямую через sqlite3
            import sqlite3

            try:
                conn = sqlite3.connect(os.path.expanduser("~/agentforge/tasks.db"))
                conn.execute(
                    "UPDATE tasks SET description = ? WHERE id = ?", (new_desc, task_id)
                )
                conn.commit()
                conn.close()
            except Exception as ex:
                log(f"⚠️ Guardian не смог обновить описание: {ex}")

            log(f"✅ Guardian вернул задачу {task_id} в очередь.")


# Счётчик циклов для периодического auto-review sweep (verify: periodic sweeps)
_review_cycle_counter = 0


def auto_review_stale():
    """Периодический sweep для подбора задач, застрявших в статусе 'review'.
    Зачем: вызов Guardian review из grok_runner.sh (или agents/grok_runner.sh)
    может потеряться (таймаут, фон, kill, crash runner'а).
    Watchdog делает независимый sweep каждые ~60 сек (6 * POLL_INTERVAL).
    Вызывает POST /review/all (см. guardian_review_all в task_queue.py).
    Это часть Guardian Self-Healing + мониторинга.
    """
    global _review_cycle_counter
    _review_cycle_counter += 1
    # Запускаем раз в 6 циклов (~60 сек при POLL_INTERVAL=10)
    if _review_cycle_counter % 6 != 0:
        return
    try:
        data = json.dumps({}).encode()
        req = urllib.request.Request(
            f"{API_BASE}/review/all",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            reviewed = result.get("reviewed", 0)
            if reviewed > 0:
                approved = sum(
                    1
                    for r in result.get("results", [])
                    if r.get("verdict") == "approved"
                )
                log(
                    f"🛡️ Auto-review sweep: {reviewed} задач проверено, {approved} одобрено"
                )
            else:
                log(
                    f"🛡️ Auto-review sweep: 0 задач в review (цикл {_review_cycle_counter})"
                )
    except Exception as e:
        log(f"⚠️ Auto-review sweep failed: {e}")


def main():
    log("🚀 Запуск AgentForge Watchdog + Guardian (core/agentforge_watchdog.py)")
    log(
        "   Мониторинг: log loop heuristics + token saving kills + Guardian self-healing (RAG retries) + periodic sweeps"
    )
    while True:
        try:
            # 1. Зацикливания (Watchdog) — log loop heuristics -> kill для экономии токенов
            tasks = get_active_tasks()
            for task in tasks:
                task_id = task["id"]
                log_path = os.path.join(LOG_DIR, f"grok_{task_id}.log")

                reason = analyze_log_for_loops(log_path)
                if reason:
                    log(
                        f"🚨 Обнаружена аномалия в {task_id}: {reason}. Принимаю меры (token-saving kill)..."
                    )
                    killed = kill_task_process(task_id)
                    mark_task_failed(task_id, reason)
                    if killed:
                        log(f"💀 Процессы задачи {task_id} убиты (сэкономлены токены).")

            # 2. Самоисцеление (Guardian) — auto-retries с RAG context
            guardian_loop()

            # 3. Подбор застрявших review-задач (periodic sweeps каждые ~60 сек)
            auto_review_stale()

        except Exception as e:
            log(f"⚠️ Глобальная ошибка: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
