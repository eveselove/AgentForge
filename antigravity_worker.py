#!/usr/bin/env python3
"""
Antigravity Worker — автономный воркер для выполнения задач на Erbox.
Работает как демон, поллит очередь AgentForge и запускает Grok CLI.
Позволяет разработке продолжаться даже при выключенном ноуте.

Запуск: python3 ~/agentforge/antigravity_worker.py
Или через systemd: systemctl start agentforge-antigravity
"""

import json
import os
import signal
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# === Конфигурация (загружается из файла или дефолты) ===
DEFAULT_CONFIG = {
    "api_base": "http://localhost:9090",
    "poll_interval": 15,
    "max_parallel": 10,
    "task_timeout": 900,
    "project_dir": "/home/eveselove/planlytasksko",
    "log_dir": "/home/eveselove/agentforge/logs",
    "grok_bin": "/home/eveselove/.grok/bin/grok",
    "default_model": "grok-3",
    "fallback_model": "grok-3",
    "agent_id": "antigravity",
}


def load_config():
    """Загрузка конфигурации из JSON файла или дефолты"""
    config_path = os.path.expanduser("~/agentforge/agentforge_config.json")
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                user_config = json.load(f)
            if "antigravity_worker" in user_config:
                config.update(user_config["antigravity_worker"])
            else:
                config.update(user_config)
        except Exception as e:
            log(f"\u26a0\ufe0f Ошибка загрузки конфига: {e}")
    return config


CFG = load_config()
API_BASE = CFG["api_base"]
POLL_INTERVAL = CFG["poll_interval"]
MAX_PARALLEL = CFG["max_parallel"]
TASK_TIMEOUT = CFG["task_timeout"]
PROJECT_DIR = CFG["project_dir"]
LOG_DIR = CFG["log_dir"]
GROK_BIN = CFG["grok_bin"]
DEFAULT_MODEL = CFG["default_model"]
FALLBACK_MODEL = CFG["fallback_model"]
AGENT_ID = CFG["agent_id"]

os.makedirs(LOG_DIR, exist_ok=True)

# Graceful shutdown
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    log("\u23f9\ufe0f Получен сигнал остановки, завершаю текущие задачи...")


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def log(msg):
    """Логирование с временной меткой"""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[AntigravityWorker {ts}] {msg}"
    print(line, flush=True)
    try:
        with open(os.path.join(LOG_DIR, "antigravity_worker.log"), "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def api_request(method, path, data=None):
    """HTTP запрос к AgentForge API"""
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, method=method)
    if data:
        req.data = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:200]
        log(f"\u26a0\ufe0f API HTTP {e.code}: {body}")
        return None
    except Exception as e:
        log(f"\u26a0\ufe0f API ошибка: {e}")
        return None


def get_tasks_for_antigravity():
    """
    Fair Work-Stealing Queue: берём задачи из общего пула (auto)
    и явно назначенные (antigravity). Задачи с pref=grok не трогаем.
    Атомарность захвата обеспечивается CAS в PATCH endpoint.
    """
    all_tasks = api_request("GET", "/tasks")
    if not all_tasks or not isinstance(all_tasks, list):
        return []

    result = []
    for t in all_tasks:
        if t.get("status") != "pending":
            continue
        pref = (t.get("preferred_agent") or "").lower()
        # Fair queue: берём auto (общий пул) и явно antigravity
        if pref not in ("antigravity", "auto", ""):
            log(f"⏭️ {t['id']} назначена {pref}, пропускаю")
            continue
        tags = t.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        tags_lower = [str(tg).lower() for tg in tags]

        if "build" in tags_lower or "compile" in tags_lower:
            continue

        result.append(t)
    return result


def select_model(task):
    """Выбор модели на основе сложности задачи"""
    complexity = (task.get("complexity") or "").lower()
    priority = (task.get("priority") or "").lower()
    if complexity == "complex" or priority == "critical":
        return FALLBACK_MODEL
    return DEFAULT_MODEL


def execute_task(task):
    """Выполнить задачу через Grok CLI с выбранной моделью"""
    task_id = task["id"]
    title = task.get("title", "")
    desc = task.get("description", "")
    priority = task.get("priority", "medium")
    tags = task.get("tags", [])
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    task_log = os.path.join(LOG_DIR, f"antigravity_{task_id}.log")
    log(f"\U0001f680 Старт задачи {task_id}: {title[:60]}")

    # Формируем промпт
    prompt = title
    if desc:
        prompt += f". Детали: {desc[:500]}"
    if tags:
        prompt += f". Теги: {','.join(tags)}"

    # Выбираем модель
    model = select_model(task)

    # Флаги Grok CLI (antigravity использует grok CLI с другой моделью)
    grok_flags = ["--always-approve"]

    # Обновляем статус → in_progress
    api_request(
        "PATCH",
        f"/tasks/{task_id}",
        {
            "status": "in_progress",
            "assigned_agent": AGENT_ID,
        },
    )

    start_time = time.time()

    GROK_BIN = CFG["grok_bin"]

    # Создаем изолированный git worktree
    branch_name = f"agentforge/{task_id}"
    worktree_dir = os.path.join(
        os.path.dirname(PROJECT_DIR), f"planlytasksko_{task_id}"
    )
    try:
        subprocess.run(
            ["git", "branch", branch_name],
            cwd=PROJECT_DIR,
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["git", "worktree", "add", worktree_dir, branch_name],
            cwd=PROJECT_DIR,
            check=False,
            capture_output=True,
        )
        log(f"🌿 Создан worktree {worktree_dir} (ветка {branch_name})")
    except Exception as e:
        log(f"⚠️ Ошибка создания worktree: {e}")
        worktree_dir = PROJECT_DIR

    # Запускаем Grok CLI с выбранной моделью
    cmd = [GROK_BIN, *grok_flags, "--cwd", worktree_dir, "-p", prompt]
    log(
        f"⚡ Antigravity запуск: {task_id} (model={model}, priority={priority}) в {worktree_dir}"
    )

    try:
        with open(task_log, "w") as logf:
            logf.write(f"[AntigravityWorker] Задача: {task_id}\n")
            logf.write(f"[AntigravityWorker] Промпт: {prompt[:300]}\n")
            logf.write(f"[AntigravityWorker] Модель: {model}\n")
            logf.write(f"[AntigravityWorker] Worktree: {worktree_dir}\n")
            logf.write(f"[AntigravityWorker] Старт: {datetime.now().isoformat()}\n\n")

            proc = subprocess.run(
                cmd,
                stdout=logf,
                stderr=subprocess.STDOUT,
                cwd=worktree_dir,
                timeout=TASK_TIMEOUT,
            )
            exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        exit_code = -9
        log(f"\u23f1\ufe0f Таймаут задачи {task_id} ({TASK_TIMEOUT}s)")
    except Exception as e:
        log(f"\u274c Ошибка запуска задачи {task_id}: {e}")
        api_request(
            "PATCH",
            f"/tasks/{task_id}",
            {
                "status": "failed",
                "result": f"AntigravityWorker: ошибка запуска — {str(e)[:200]}",
                "assigned_agent": AGENT_ID,
            },
        )
        return

    duration = time.time() - start_time

    # Определяем результат
    if exit_code == -9 or duration >= TASK_TIMEOUT:
        status = "failed"
        result = f"AntigravityWorker: timeout ({int(duration)}s, model={model})"
    elif exit_code != 0 or duration <= 3:
        status = "failed"
        result = f"AntigravityWorker: exit={exit_code}, {int(duration)}s, model={model}"
    else:
        status = "review"
        result = f"AntigravityWorker: {int(duration)}s (model={model}) \u2705"

    # Обновляем задачу
    api_request(
        "PATCH",
        f"/tasks/{task_id}",
        {
            "status": status,
            "result": result,
            "assigned_agent": AGENT_ID,
            "duration_seconds": round(duration, 1),
        },
    )

    icon = "\u2705" if status == "review" else "\u274c"
    log(f"{icon} {task_id}: {result}")

    # Guardian auto-review для успешных
    if status == "review":
        time.sleep(1)
        api_request("POST", f"/tasks/{task_id}/review")
        log(f"\U0001f6e1\ufe0f Guardian запрошен для {task_id}")

    # Auto-retry для failed (если включено)
    if status == "failed":
        api_request("POST", f"/tasks/{task_id}/retry")
        log(f"\U0001f504 Auto-retry запрошен для {task_id}")


def main():
    """Главный цикл воркера с ThreadPoolExecutor"""
    log("\U0001f680 Antigravity Worker запущен")
    log(f"   API: {API_BASE}")
    log(f"   Параллельность: {MAX_PARALLEL}")
    log(f"   Таймаут: {TASK_TIMEOUT}s")
    log(f"   Модель: {DEFAULT_MODEL} (fallback: {FALLBACK_MODEL})")
    log(f"   Проект: {PROJECT_DIR}")

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as executor:
        futures = {}  # future → task_id

        while not _shutdown:
            try:
                # Очищаем завершённые
                done_futures = [f for f in futures if f.done()]
                for f in done_futures:
                    tid = futures.pop(f)
                    try:
                        f.result()  # Проверяем исключения
                    except Exception as e:
                        log(f"\u274c Ошибка в задаче {tid}: {e}")

                # Сколько слотов свободно?
                free_slots = MAX_PARALLEL - len(futures)
                if free_slots <= 0:
                    time.sleep(5)
                    continue

                # Получаем задачи для Antigravity
                tasks = get_tasks_for_antigravity()

                if not tasks:
                    time.sleep(POLL_INTERVAL)
                    continue

                log(
                    f"\U0001f4cb Найдено {len(tasks)} задач, свободно {free_slots} слотов"
                )

                for task in tasks[:free_slots]:
                    task_id = task["id"]

                    # Атомарно захватываем задачу через PATCH (не dispatch!)
                    # dispatch всегда назначает grok через resolve_agent,
                    # поэтому antigravity напрямую ставит себя как assigned_agent
                    claim_result = api_request(
                        "PATCH",
                        f"/tasks/{task_id}",
                        {
                            "status": "in_progress",
                            "assigned_agent": AGENT_ID,
                        },
                    )
                    if not claim_result:
                        continue

                    # Проверяем что мы действительно захватили (не другой агент)
                    claimed_agent = (claim_result.get("assigned_agent") or "").lower()
                    claimed_status = (claim_result.get("status") or "").lower()
                    if claimed_status != "in_progress" or claimed_agent != AGENT_ID:
                        log(f"⏭️ {task_id} уже захвачена ({claimed_agent}), пропускаю")
                        continue

                    # Запускаем в пуле потоков
                    future = executor.submit(execute_task, task)
                    futures[future] = task_id
                    log(f"🔀 Задача {task_id} запущена в потоке")
                    time.sleep(1)

            except Exception as e:
                log(f"\u26a0\ufe0f Ошибка в главном цикле: {e}")
                time.sleep(POLL_INTERVAL)

    # Ждём завершения текущих задач
    log("\u23f3 Ожидаю завершения текущих задач...")
    for f in futures:
        try:
            f.result(timeout=60)
        except Exception:
            pass
    log("\U0001f6d1 Antigravity Worker остановлен")


if __name__ == "__main__":
    main()
