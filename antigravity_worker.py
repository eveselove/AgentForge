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
import random
import signal
import subprocess
import threading
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Глобальная сессия для переиспользования TCP-соединений (Keep-Alive)
_session = requests.Session()

# === Конфигурация (загружается из файла или дефолты) ===
DEFAULT_CONFIG = {
    "api_base": "http://localhost:9090",
    "poll_interval": 15,
    "max_parallel": 10,
    "task_timeout": 1800,
    "project_dir": "/home/eveselove/agentforge",
    "log_dir": "/home/eveselove/agentforge/logs",
    "agy_bin": "/home/eveselove/.local/bin/agy",
    "agent_id": "antigravity",
}

# === 3 группы моделей Antigravity CLI (agy) — 3 разных лимита ===
# У каждой группы свой независимый rate limit.
# При исчерпании лимита группа уходит на cooldown, следующая вступает.
# Порядок замещения (fallback_order):
#   Claude исчерпан → Flash → Pro
#   Flash исчерпан  → Pro   → Claude
#   Pro исчерпан    → Flash → Claude
MODEL_GROUPS = [
    {
        "name": "A-gemini-pro-high",
        "model": "Gemini 3.1 Pro (High)",
        "cooldown": 120,
        "fallback_order": [1],     # при лимите: Opus
    },
    {
        "name": "B-claude-opus",
        "model": "Claude Opus 4.6 (Thinking)",
        "cooldown": 300,
        "fallback_order": [0],     # при лимите: Gemini Pro High
    },
]

# Глобальное состояние rate-limit для каждой группы (thread-safe)
_rate_limit_lock = threading.Lock()
_rate_limit_until = {}   # group_name → timestamp когда cooldown истекает
_current_group_idx = 0   # текущая предпочтительная группа


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
API_BASE = os.environ.get("AGENTFORGE_API", CFG["api_base"])
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", CFG["poll_interval"]))
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", CFG["max_parallel"]))
TASK_TIMEOUT = int(os.environ.get("TASK_TIMEOUT", CFG["task_timeout"]))
PROJECT_DIR = os.environ.get("PROJECT_DIR", CFG["project_dir"])
LOG_DIR = os.environ.get("LOG_DIR", CFG["log_dir"])
AGY_BIN = os.environ.get("AGY_BIN", CFG.get("agy_bin", "/home/eveselove/.local/bin/agy"))
AGENT_ID = os.environ.get("AGENT_ID", CFG["agent_id"])

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


def api_request(method, path, data=None, timeout=30):
    """HTTP запрос к AgentForge API через Keep-Alive сессию"""
    url = f"{API_BASE}{path}"
    try:
        resp = _session.request(method, url, json=data, timeout=timeout)
        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            log(f"⚠️ API HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()
    except requests.RequestException as e:
        log(f"⚠️ API ошибка сети: {e}")
        return None


def select_model(task):
    """
    Выбор модели с учётом rate-limit cooldown по группам.

    Логика:
    1. Определяем предпочтительную группу по сложности задачи
    2. Если предпочтительная группа на cooldown — берём из её fallback_order
    3. Если все группы на cooldown — ждём ту, у которой cooldown истекает раньше

    Порядок замещения:
      Flash исчерпан  → Pro → Claude
      Pro исчерпан    → Flash → Claude
      Claude исчерпан → Flash → Pro
    """
    global _current_group_idx
    complexity = (task.get("complexity") or "").lower()
    priority = (task.get("priority") or "").lower()
    tags = task.get("tags", [])
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []
    tags_lower = [str(t).lower() for t in tags]

    # Определяем предпочтительную группу по сложности задачи
    COMPLEX_TAGS = {"architecture", "analysis", "refactor", "complex",
                    "security", "perf", "performance", "design", "protocol"}
    if complexity == "complex" or priority == "critical" or any(t in COMPLEX_TAGS for t in tags_lower):
        preferred_group = 1  # B-claude-opus
    else:
        preferred_group = 0  # A-gemini-pro-high

    now = time.time()
    with _rate_limit_lock:
        # Порядок: preferred → fallback_order этой группы (не глобальный round-robin)
        preferred = MODEL_GROUPS[preferred_group]
        order = [preferred_group] + preferred.get("fallback_order", [
            i for i in range(len(MODEL_GROUPS)) if i != preferred_group
        ])

        for idx in order:
            grp = MODEL_GROUPS[idx]
            until = _rate_limit_until.get(grp["name"], 0)
            if now >= until:
                model = grp["model"]
                if idx != preferred_group:
                    log(f"🔀 Замещение: {preferred['name']} на cooldown → {grp['name']} ({model})")
                else:
                    log(f"🎲 Модель: {model} (группа {grp['name']})")
                return model

        # Все группы на cooldown — ждём ту, у которой cooldown истекает раньше
        best_idx = min(range(len(MODEL_GROUPS)),
                       key=lambda i: _rate_limit_until.get(MODEL_GROUPS[i]["name"], 0))
        grp = MODEL_GROUPS[best_idx]
        wait = max(0, _rate_limit_until.get(grp["name"], 0) - now)
        log(f"⏳ Все группы на cooldown, жду {wait:.0f}s → {grp['name']} ({grp['model']})")
        time.sleep(wait + 1)
        return grp["model"]


def detect_rate_limit(log_path, exit_code, duration):
    """
    Определяет тип завершения задачи:
    - 'rate_limit': hit rate limit (задача слишком быстрая или сообщение в логе)
    - 'timeout': таймаут
    - 'error': ошибка
    - 'success': успех
    """
    # Быстрое завершение (<5s) = почти всегда rate limit или auth error
    if 0 < duration <= 5 and exit_code != 0:
        return 'rate_limit'

    # Проверяем лог на признаки rate limit
    rate_limit_markers = [
        'rate limit', 'rate_limit', '429', 'too many requests',
        'quota exceeded', 'quota_exceeded', 'limit exceeded',
        'throttled', 'slowdown', 'ratelimit',
    ]
    try:
        with open(log_path, 'r', errors='ignore') as f:
            content = f.read(4096).lower()  # Читаем только начало
        for marker in rate_limit_markers:
            if marker in content:
                return 'rate_limit'
    except Exception:
        pass

    if exit_code == -9 or duration >= TASK_TIMEOUT:
        return 'timeout'
    if exit_code != 0:
        return 'error'
    return 'success'


def apply_rate_limit_cooldown(model):
    """Ставим cooldown на группу модели после rate limit"""
    with _rate_limit_lock:
        for grp in MODEL_GROUPS:
            if model == grp["model"]:
                until = time.time() + grp["cooldown"]
                _rate_limit_until[grp["name"]] = until
                log(f"🚫 Rate limit: группа {grp['name']} ({model}) на cooldown {grp['cooldown']}s")
                return
    log(f"⚠️ Модель {model} не найдена в группах, cooldown не применён")


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

    # Флаги Antigravity CLI (agy)
    # --add-dir worktree: agy знает о worktree файлах, но запускается из PROJECT_DIR (где есть auth)
    agy_flags = ["--dangerously-skip-permissions", "--model", model]

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

    # Создаем изолированный git worktree
    branch_name = f"agentforge/{task_id}"
    proj_name = os.path.basename(PROJECT_DIR)
    worktree_dir = os.path.join(
        os.path.dirname(PROJECT_DIR), f"{proj_name}_{task_id}"
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

    # Запускаем Antigravity CLI (agy) из PROJECT_DIR (где есть auth)
    # --add-dir worktree_dir: даёт agy доступ к файлам в изолированном worktree
    run_from = PROJECT_DIR  # запускаем отсюда — здесь есть OAuth токен
    if worktree_dir != PROJECT_DIR:
        # В промпте явно указываем worktree чтобы агент работал в нём
        full_prompt = f"WORKING DIRECTORY: {worktree_dir}\n\n{prompt}"
        cmd = [AGY_BIN, *agy_flags, "--add-dir", worktree_dir, "--print", full_prompt]
    else:
        full_prompt = prompt
        cmd = [AGY_BIN, *agy_flags, "--print", full_prompt]
    log(
        f"⚡ AGY запуск: {task_id} (model={model}, priority={priority}) worktree={worktree_dir}"
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
                cwd=run_from,        # запуск из PROJECT_DIR — там есть auth
                env={
                    **os.environ,
                    "HOME": os.path.expanduser("~"),  # гарантируем HOME
                    "SSH_TTY": os.environ.get("SSH_TTY", "/dev/pts/0"),  # file-based token (не keyring)
                },
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

    try:
        # Детектируем тип завершения (в т.ч. rate limit)
        finish_type = detect_rate_limit(task_log, exit_code, duration)

        if finish_type == 'rate_limit':
            # Rate limit: применяем cooldown на эту группу моделей
            apply_rate_limit_cooldown(model)
            # Возвращаем задачу в pending чтобы другой воркер/модель подхватила
            log(f"⚡ Rate limit на {model}, возвращаю {task_id} в pending")
            api_request(
                "PATCH",
                f"/tasks/{task_id}",
                {
                    "status": "pending",
                    "assigned_agent": None,
                    "result": f"rate_limit:{model}:{int(duration)}s — переключаю модель",
                },
            )
            return
        elif finish_type == 'timeout':
            status = "failed"
            result = f"AntigravityWorker: timeout ({int(duration)}s, model={model})"
        elif finish_type == 'error':
            status = "failed"
            result = f"AntigravityWorker: exit={exit_code}, {int(duration)}s, model={model}"
        else:  # success
            status = "review"
            result = f"AntigravityWorker: {int(duration)}s (model={model}) ✅"

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

        icon = "✅" if status == "review" else "❌"
        log(f"{icon} {task_id}: {result}")

        # Guardian auto-review для успешных
        if status == "review":
            time.sleep(1)
            api_request("POST", f"/tasks/{task_id}/review")
            log(f"🛡️ Guardian запрошен для {task_id}")

        # Auto-retry для failed
        if status == "failed":
            api_request("POST", f"/tasks/{task_id}/retry")
            log(f"🔄 Auto-retry запрошен для {task_id}")
            
    finally:
        # Cleanup worktree
        if worktree_dir != PROJECT_DIR and os.path.exists(worktree_dir):
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "-f", worktree_dir],
                    cwd=PROJECT_DIR,
                    check=False,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "branch", "-D", branch_name],
                    cwd=PROJECT_DIR,
                    check=False,
                    capture_output=True,
                )
                log(f"🧹 Worktree и ветка {branch_name} удалены")
            except Exception as e:
                log(f"⚠️ Ошибка удаления worktree {worktree_dir}: {e}")



def main():
    """Главный цикл воркера с ThreadPoolExecutor"""
    log("🚀 Antigravity Worker запущен (agy + Model Rate-Limit Rotation)")
    log(f"   API: {API_BASE}")
    log(f"   Параллельность: {MAX_PARALLEL}")
    log(f"   Таймаут: {TASK_TIMEOUT}s")
    log(f"   AGY bin: {AGY_BIN}")
    log(f"   Проект: {PROJECT_DIR}")
    for grp in MODEL_GROUPS:
        log(f"   Группа {grp['name']}: model={grp['model']} cooldown={grp['cooldown']}s")

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

                # === Получаем задачи по 1 атомарно через POST /claim ===
                claimed_any = False
                for _ in range(free_slots):
                    if _shutdown:
                        break
                        
                    claim_result = api_request(
                        "POST",
                        "/claim",
                        {"agent": AGENT_ID}
                    )
                    
                    if not claim_result:
                        break # Очередь пуста
                        
                    task_id = claim_result["id"]
                    log(f"🎯 Claim: {task_id} — {claim_result.get('title', '')[:60]}")
                    
                    future = executor.submit(execute_task, claim_result)
                    futures[future] = task_id
                    claimed_any = True
                    time.sleep(1) # Небольшая пауза между стартами
                    
                if not claimed_any:
                    time.sleep(POLL_INTERVAL + random.uniform(0, POLL_INTERVAL * 0.3))

            except Exception as e:
                log(f"\u26a0\ufe0f Ошибка в главном цикле: {e}")
                time.sleep(POLL_INTERVAL + random.uniform(0, 10))

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
