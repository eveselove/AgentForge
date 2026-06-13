#!/usr/bin/env python3
"""
Builder Worker — автономный воркер для конвейерной сборки (CI/CD) в AgentForge.
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
import shutil
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# === Конфигурация ===
DEFAULT_CONFIG = {
    "api_base": "http://localhost:9090",
    "poll_interval": 10,
    "max_parallel": 2,  # Билдеру даём 2 потока
    "task_timeout": 600,
    "project_dir": "/home/eveselove/planlytasksko",
    "log_dir": "/home/eveselove/agentforge/logs",
    "agent_id": "builder",
}

def load_config():
    config_path = os.path.expanduser("~/agentforge/agentforge_config.json")
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                user_config = json.load(f)
            if "builder_worker" in user_config:
                config.update(user_config["builder_worker"])
        except Exception:
            pass
    return config

CFG = load_config()
API_BASE = CFG["api_base"]
POLL_INTERVAL = CFG["poll_interval"]
MAX_PARALLEL = CFG["max_parallel"]
TASK_TIMEOUT = CFG["task_timeout"]
PROJECT_DIR = CFG["project_dir"]
LOG_DIR = CFG["log_dir"]
AGENT_ID = CFG["agent_id"]

os.makedirs(LOG_DIR, exist_ok=True)

_shutdown = False
def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    log("⏹️ Получен сигнал остановки...")

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[BuilderWorker {ts}] {msg}"
    print(line, flush=True)
    try:
        with open(os.path.join(LOG_DIR, "builder_worker.log"), "a") as f:
            f.write(line + "\n")
    except: pass

def api_request(method, path, data=None):
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, method=method)
    if data:
        req.data = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log(f"⚠️ API ошибка {path}: {e}")
        return None

def get_tasks_for_builder():
    all_tasks = api_request("GET", "/tasks")
    if not all_tasks or not isinstance(all_tasks, list):
        return []
    result = []
    for t in all_tasks:
        if t.get("status") != "pending":
            continue
        pref = (t.get("preferred_agent") or "").lower()
        tags = t.get("tags", [])
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except: tags = []
        tags_lower = [str(tg).lower() for tg in tags]
        
        if pref == "builder" or "build" in tags_lower or "compile" in tags_lower:
            result.append(t)
    return result

def execute_build(task):
    task_id = task["id"]
    git_branch = task.get("git_branch")
    
    if not git_branch:
        api_request("PATCH", f"/tasks/{task_id}", {
            "status": "failed", "result": "No git_branch specified for build", "assigned_agent": AGENT_ID
        })
        return

    log(f"🚀 Старт сборки: {task_id} ветка {git_branch}")
    api_request("PATCH", f"/tasks/{task_id}", {"status": "in_progress", "assigned_agent": AGENT_ID})
    
    start_time = time.time()
    worktree_dir = os.path.join(os.path.dirname(PROJECT_DIR), f"planlytasksko_build_{task_id}")
    
    try:
        # Пытаемся создать worktree
        subprocess.run(["git", "worktree", "add", worktree_dir, git_branch], cwd=PROJECT_DIR, check=False, capture_output=True)
        log(f"🌿 Создан worktree {worktree_dir}")
    except Exception as e:
        log(f"⚠️ Ошибка создания worktree: {e}")
        api_request("PATCH", f"/tasks/{task_id}", {"status": "failed", "result": "Git worktree error"})
        return

    # Динамический выбор команды сборки
    build_cmd = ["cargo", "check"]
    test_cmd = ["cargo", "test"]
    if os.path.exists(os.path.join(worktree_dir, "package.json")):
        build_cmd = ["npm", "install"]
        test_cmd = ["npm", "run", "build"]

    task_log = os.path.join(LOG_DIR, f"builder_{task_id}.log")
    exit_code = 0
    duration = 0
    try:
        with open(task_log, "w") as logf:
            logf.write(f"--- Сборка ---\n")
            p1 = subprocess.run(build_cmd, cwd=worktree_dir, stdout=logf, stderr=subprocess.STDOUT, timeout=TASK_TIMEOUT)
            if p1.returncode == 0:
                logf.write(f"--- Тесты ---\n")
                p2 = subprocess.run(test_cmd, cwd=worktree_dir, stdout=logf, stderr=subprocess.STDOUT, timeout=TASK_TIMEOUT)
                exit_code = p2.returncode
            else:
                exit_code = p1.returncode
    except subprocess.TimeoutExpired:
        exit_code = -9
    except Exception as e:
        exit_code = 1
        with open(task_log, "a") as logf: logf.write(f"\nError: {e}")

    duration = time.time() - start_time

    # Чтение последних строк лога для ошибки
    error_snippet = ""
    if exit_code != 0:
        try:
            with open(task_log, "r") as logf:
                lines = logf.readlines()
                error_snippet = "".join(lines[-50:])
        except: pass

    # Удаление worktree после сборки
    subprocess.run(["git", "worktree", "remove", "--force", worktree_dir], cwd=PROJECT_DIR, check=False)

    if exit_code == 0:
        log(f"✅ Сборка {task_id} успешна")
        api_request("PATCH", f"/tasks/{task_id}", {
            "status": "review", "result": "Build and tests passed successfully", "assigned_agent": AGENT_ID, "duration_seconds": round(duration, 1)
        })
    else:
        log(f"❌ Сборка {task_id} упала. Создаю задачу на исправление.")
        api_request("PATCH", f"/tasks/{task_id}", {
            "status": "failed", "result": f"Build failed (exit {exit_code})", "assigned_agent": AGENT_ID, "duration_seconds": round(duration, 1)
        })
        # Создаем задачу на исправление
        api_request("POST", "/tasks", {
            "title": f"Исправить ошибку компиляции: {git_branch}",
            "description": f"Ветка `{git_branch}` не собирается.\n\nЛог ошибки:\n```\n{error_snippet}\n```\nПожалуйста, исправь код.",
            "preferred_agent": "auto",
            "priority": "high",
            "complexity": "simple",
            "tags": ["fix", "build"],
            "git_branch": git_branch
        })

def main():
    log("🚀 Builder Worker запущен")
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as executor:
        futures = {}
        while not _shutdown:
            try:
                done_futures = [f for f in futures if f.done()]
                for f in done_futures:
                    tid = futures.pop(f)
                    try: f.result()
                    except Exception as e: log(f"❌ Ошибка в задаче {tid}: {e}")

                free_slots = MAX_PARALLEL - len(futures)
                if free_slots <= 0:
                    time.sleep(5)
                    continue

                tasks = get_tasks_for_builder()
                if not tasks:
                    time.sleep(POLL_INTERVAL)
                    continue

                for task in tasks[:free_slots]:
                    task_id = task["id"]
                    dispatch_result = api_request("POST", f"/tasks/{task_id}/dispatch")
                    if not dispatch_result: continue
                    assigned = (dispatch_result.get("assigned_agent") or "").lower()
                    if assigned != AGENT_ID: continue

                    future = executor.submit(execute_build, task)
                    futures[future] = task_id
                    time.sleep(1)
            except Exception as e:
                log(f"⚠️ Ошибка цикла: {e}")
                time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
