#!/usr/bin/env python3
"""
AgentForge Watchdog & Guardian Daemon
Мониторит активные задачи и убивает зациклившиеся процессы агентов для экономии токенов.
Также выполняет роль Guardian: воскрешает упавшие задачи с добавлением RAG-контекста.
"""

import time
import json
import urllib.request
import urllib.error
import os
import subprocess
from collections import Counter
import re
import sys

# Добавляем путь к planlytasksko для импорта task_checkpoints
import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from scripts.task_checkpoints import get_last_checkpoint, search_similar_tasks
except ImportError:
    get_last_checkpoint = None
    search_similar_tasks = None

API_BASE = "http://localhost:8080"
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
POLL_INTERVAL = 10
LOOP_THRESHOLD = 5 # Если одинаковая строка-ошибка или шаблон появляется >5 раз
MAX_LOG_SIZE_MB = 2.0 # Лимит размера лога (защита от спама)

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
            method="PATCH"
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
    """Найти и убить процесс grok, связанный с задачей (через worktree dir)"""
    worktree_dir = f"agentforge-{task_id}"
    try:
        cmd = ["pgrep", "-f", worktree_dir]
        result = subprocess.run(cmd, capture_output=True, text=True)
        pids = result.stdout.strip().split("\n")
        
        killed = False
        for pid in pids:
            if pid:
                subprocess.run(["kill", "-9", pid], check=False)
                killed = True
                
        cmd2 = ["pgrep", "-f", f"grok_worker.*{task_id}|grok.*{task_id}"]
        res2 = subprocess.run(cmd2, capture_output=True, text=True)
        for pid in res2.stdout.strip().split("\n"):
            if pid:
                subprocess.run(["kill", "-9", pid], check=False)
                killed = True
                
        return killed
    except Exception as e:
        log(f"⚠️ Ошибка при убийстве процесса: {e}")
        return False

def mark_task_failed(task_id, reason):
    """Перевести задачу в статус failed"""
    payload = {
        "status": "failed",
        "result": f"[Watchdog] 🛑 Принудительно остановлено: {reason}. Сэкономлены токены."
    }
    api_patch(f"/tasks/{task_id}", payload)
    log(f"✅ Задача {task_id} помечена как failed.")

def analyze_log_for_loops(log_path):
    """Эвристический анализ лога на бесконечные циклы"""
    if not os.path.exists(log_path):
        return None
        
    try:
        size_mb = os.path.getsize(log_path) / (1024 * 1024)
        if size_mb > MAX_LOG_SIZE_MB:
            return f"превышен лимит лога ({size_mb:.1f} MB)"

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            
        if not lines:
            return None
            
        recent_lines = [l.strip() for l in lines[-50:] if l.strip()]
        error_lines = [l for l in recent_lines if "error" in l.lower() or "failed" in l.lower() or "exception" in l.lower()]
        if error_lines:
            counts = Counter(error_lines)
            most_common, count = counts.most_common(1)[0]
            if count >= LOOP_THRESHOLD:
                return f"зацикливание ошибки ('{most_common[:50]}...')"
                
        tool_calls = [l for l in recent_lines if "Running tool" in l or "Command output" in l]
        if len(tool_calls) > 20: 
            counts = Counter(tool_calls)
            if counts and counts.most_common(1)[0][1] >= LOOP_THRESHOLD:
                return "зацикливание вызова инструментов"
                
        return None
    except Exception as e:
        log(f"⚠️ Ошибка анализа {log_path}: {e}")
        return None

def guardian_loop():
    """Проверяет упавшие задачи и пытается их воскресить с RAG-контекстом"""
    if not get_last_checkpoint:
        return
        
    failed_tasks = get_failed_tasks()
    for task in failed_tasks:
        task_id = task["id"]
        retry_count = task.get("retry_count", 0)
        
        if retry_count < 3:
            log(f"🛡️ Guardian: Воскрешение задачи {task_id} (Попытка {retry_count + 1}/3)")
            
            error_msg = task.get("result", "")
            
            # Попытаемся достать ошибку из чекпоинтов
            cp = get_last_checkpoint(task_id)
            if cp and cp.get("data", {}).get("error"):
                error_msg = cp["data"]["error"]
            
            # RAG поиск
            rag_context = ""
            if search_similar_tasks and error_msg:
                # Ищем похожие задачи по тексту ошибки
                similar = search_similar_tasks(str(error_msg)[:200], limit=3)
                if similar:
                    rag_context = "\n\n--- GUARDIAN RAG CONTEXT ---\nНайдено несколько похожих прошлых задач, которые могут помочь решить эту ошибку:\n"
                    for s in similar:
                        outcome = s.get('outcome', 'unknown')
                        rag_context += f"- Задача '{s.get('title')}': Статус: {outcome}.\n"
            
            new_desc = task.get("description", "")
            guardian_note = f"\n\n--- GUARDIAN AUTO-RETRY ({retry_count + 1}/3) ---\nПредыдущая попытка завершилась ошибкой:\n{error_msg}{rag_context}"
            
            # Избегаем дублирования логов
            if "--- GUARDIAN AUTO-RETRY" in new_desc:
                new_desc = new_desc.split("--- GUARDIAN AUTO-RETRY")[0].strip()
                
            new_desc += guardian_note
            
            # Патчим базу: статус -> pending, обновляем счетчик и описание
            api_patch(f"/tasks/{task_id}", {
                "status": "pending",
                "retry_count": retry_count + 1,
                "result": None # Clear previous failure result
            })
            
            # Поскольку API не поддерживает обновление description, мы обновим его напрямую через sqlite3
            import sqlite3
            try:
                conn = sqlite3.connect("/home/eveselove/planlytasksko/data/tasks.db")
                conn.execute("UPDATE tasks SET description = ? WHERE id = ?", (new_desc, task_id))
                conn.commit()
                conn.close()
            except Exception as ex:
                log(f"⚠️ Guardian не смог обновить описание: {ex}")
                
            log(f"✅ Guardian вернул задачу {task_id} в очередь.")

# Счётчик циклов для периодического auto-review
_review_cycle_counter = 0

def auto_review_stale():
    """Подбирает задачи, застрявшие в статусе review.
    Guardian вызов из grok_runner.sh может потеряться (фон, таймаут),
    поэтому Watchdog периодически делает sweep."""
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
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            reviewed = result.get("reviewed", 0)
            if reviewed > 0:
                approved = sum(1 for r in result.get("results", []) if r.get("verdict") == "approved")
                log(f"🛡️ Auto-review sweep: {reviewed} задач проверено, {approved} одобрено")
    except Exception as e:
        log(f"⚠️ Auto-review sweep failed: {e}")

def main():
    log("🚀 Запуск AgentForge Watchdog + Guardian")
    while True:
        try:
            # 1. Зацикливания (Watchdog)
            tasks = get_active_tasks()
            for task in tasks:
                task_id = task["id"]
                log_path = os.path.join(LOG_DIR, f"grok_{task_id}.log")
                
                reason = analyze_log_for_loops(log_path)
                if reason:
                    log(f"🚨 Обнаружена аномалия в {task_id}: {reason}. Принимаю меры...")
                    killed = kill_task_process(task_id)
                    mark_task_failed(task_id, reason)
                    if killed:
                        log(f"💀 Процессы задачи {task_id} убиты.")
                        
            # 2. Самоисцеление (Guardian)
            guardian_loop()
            
            # 3. Подбор застрявших review-задач (sweep каждые ~60 сек)
            auto_review_stale()
            
        except Exception as e:
            log(f"⚠️ Глобальная ошибка: {e}")
            
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
