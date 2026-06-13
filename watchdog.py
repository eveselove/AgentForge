#!/usr/bin/env python3
"""
AgentForge Watchdog & Guardian Daemon
Мониторит активные задачи и убивает зациклившиеся процессы агентов для экономии токенов.
Также выполняет роль Guardian: воскрешает упавшие задачи с добавлением RAG-контекста.

!!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
WATCHDOG FLYWHEEL MONITORING BITS DEPRECATED.
Python flywheel orchestration (continuous, step triggers, candidate mgmt) fully deprecated.
Watchdog flywheel-related health/monitoring paths will be replaced by Rust agentforge-runner health + direct logs.
Migrate monitoring to: agentforge-runner continuous (health JSON) + cargo-native observability.
See PHASE4_REMOVAL_PLAN.md for removal order (Tier 3/4), risks, rollback.
Non-flywheel watchdog/guardian core may remain longer.
"""

import time
import json
import urllib.request
import urllib.error
import os
import subprocess
from collections import Counter
import sys

# Добавляем путь к planlytasksko / agentforge для импорта task_checkpoints (RAG для Guardian)
# Исправлено (audit): более робастный поиск, как в core/agentforge_watchdog.py
for p in [
    "/data/planlytasksko",
    "/home/eveselove/planlytasksko",
    os.path.expanduser("~/planlytasksko"),
    "/home/eveselove/agentforge",
    os.path.expanduser("~/agentforge"),
]:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)
    core_p = os.path.join(p, "core") if os.path.exists(p) else ""
    if core_p and os.path.exists(core_p) and core_p not in sys.path:
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
LOG_DIR = os.path.expanduser("~/agentforge/logs")
POLL_INTERVAL = 30  # Увеличено с 10 до 30 (мониторинг не требует частого опроса)
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
        "result": f"[Watchdog] 🛑 Принудительно остановлено: {reason}. Сэкономлены токены.",
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

        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        if not lines:
            return None

        recent_lines = [l.strip() for l in lines[-50:] if l.strip()]
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

        tool_calls = [
            l for l in recent_lines if "Running tool" in l or "Command output" in l
        ]
        if len(tool_calls) > 20:  # noqa: E501 (long for clarity)
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
            log(
                f"🛡️ Guardian: Воскрешение задачи {task_id} (Попытка {retry_count + 1}/3)"
            )

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
                        outcome = s.get("outcome", "unknown")
                        rag_context += (
                            f"- Задача '{s.get('title')}': Статус: {outcome}.\n"
                        )

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


def _flywheel_health_report():
    """Autonomy hook: surface Rust flywheel health (candidates generated last hour, last A/B, high-LV pending).
    Called on every watchdog poll. Writes compact status + logs summary. Non-fatal, reuses continuous health file + pending_candidates prioritizer.
    Evidence of continuous loop running 24/7 without manual triggers.

    DEEP TIMER INTEGRATION (Autonomy Timer Production Rolled Out):
    - Probes both --user and system for agentforge-flywheel.timer status (active/inactive, next/last trigger).
    - Uses subprocess + timeout to avoid hangs.
    - Enriches watchdog_flywheel_status.json and logs with timer pulse (e.g. "timer=active next=18.2min").
    - Full reuse of ENABLE_RUST_FLYWHEEL patterns; never breaks core watchdog.
    """
    try:
        import json
        import subprocess
        from pathlib import Path
        from datetime import datetime

        state_dir = Path("/tmp/agentforge_rust_flywheel")
        health_p = state_dir / "flywheel_health.json"
        health = {}
        if health_p.exists():
            try:
                health = json.loads(health_p.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Fallback live count via prioritizer (even if continuous not run yet)
        last_hour = health.get("candidates_last_hour", 0)
        high_lv = health.get("high_lv_pending", 0)
        last_ab_age = health.get("last_ab_age_min")

        # === SAFEGUARDS & MONITORING: Rich export health section (for default Rust Flywheel safety) ===
        rich = health.get("rich_exports") or {}
        rich_sr = rich.get("success_rate", None)
        rich_err_rate = rich.get("error_rate", None)
        rich_consec = int(rich.get("consecutive_failures", 0) or 0)
        rich_last_succ = rich.get("last_success_iso") or rich.get("last_success_unix")
        rich_total = rich.get("total_attempts", 0)
        degraded = health.get("degraded", False)
        degraded_reason = health.get("degraded_reason")

        # Auto-disable / graceful degradation logic (simple, production-grade)
        # If too many consecutive rich export failures OR no successful rich export for hours -> warn + suggest disable
        AUTO_DISABLE_CONSEC = 5
        AUTO_DISABLE_STALE_HOURS = 8
        flywheel_safeguard_msg = None
        if degraded or rich_consec >= AUTO_DISABLE_CONSEC:
            flywheel_safeguard_msg = (
                f"⚠️ FLYWHEEL DEGRADED (rich_exports): consec_fails={rich_consec} sr={rich_sr} "
                f"reason={degraded_reason or 'high_consec'} — suggest export DISABLE_RUST_FLYWHEEL=1 "
                "or touch /tmp/.../DISABLE_FLYWHEEL for graceful off. (default remains safe via monitoring)"
            )
            log(flywheel_safeguard_msg)
        elif rich_total > 3 and rich_last_succ:
            # lightweight stale check (reuse health ts if needed)
            try:
                # rough: if last_success age >8h (unix or parse)
                ls = rich.get("last_success_unix")
                if ls and (time.time() - float(ls) > AUTO_DISABLE_STALE_HOURS * 3600):
                    flywheel_safeguard_msg = (
                        f"⚠️ FLYWHEEL STALE rich_exports (no success >{AUTO_DISABLE_STALE_HOURS}h, total={rich_total}) — "
                        "log only; suggest DISABLE_RUST_FLYWHEEL=1 if persistent. Continuous timer will force safe mode."
                    )
                    log(flywheel_safeguard_msg)
            except Exception:
                pass

        # === DEEP TIMER HEALTH (production rollout) ===
        timer_info = {
            "mode": None,
            "active": False,
            "next": None,
            "last": None,
            "status": "unknown",
        }
        for mode, cmd_prefix in [
            ("user", ["systemctl", "--user"]),
            ("system", ["systemctl"]),
        ]:
            try:
                # Check if unit exists and get status (timeout protected, 3s max)
                unit = "agentforge-flywheel.timer"
                # is-active
                res = subprocess.run(
                    cmd_prefix + ["is-active", unit],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                is_active = res.stdout.strip() == "active"
                # show for timing info (NextElapse etc are monotonic but useful for parse; use list-timers for human)
                show_res = subprocess.run(
                    cmd_prefix
                    + [
                        "show",
                        unit,
                        "--property=ActiveState,NextElapseUSecMonotonic,LastTriggerUSec",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                props = {}
                for line in show_res.stdout.strip().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        props[k] = v
                # Fallback human next via list-timers (greppable)
                list_res = subprocess.run(
                    cmd_prefix + ["list-timers", "--all", "--no-pager"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                )
                next_human = None
                for ln in list_res.stdout.splitlines():
                    if "agentforge-flywheel" in ln:
                        parts = ln.split()
                        if len(parts) >= 1:
                            next_human = " ".join(
                                parts[:4]
                            )  # e.g. "Tue 2026-06-02 ..."
                        break
                if is_active or "agentforge-flywheel" in list_res.stdout:
                    timer_info = {
                        "mode": mode,
                        "active": is_active,
                        "next": next_human or props.get("NextElapseUSecMonotonic"),
                        "last": props.get("LastTriggerUSec"),
                        "status": "active" if is_active else "inactive",
                    }
                    break  # prefer first hit (user over system, or whichever responds)
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                continue

        # Also touch a lightweight status for external monitors
        status = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "flywheel_candidates_last_hour": last_hour,
            "flywheel_high_lv_pending": high_lv,
            "last_ab_age_min": last_ab_age,
            "continuous_last_run": (health.get("last_continuous") or {}).get(
                "finished_at"
            ),
            "enable_marker": (
                state_dir.parent / "agentforge/ENABLE_RUST_FLYWHEEL"
            ).exists()
            or Path(os.path.expanduser("~/agentforge/ENABLE_RUST_FLYWHEEL")).exists(),
            # Deep timer rollout fields:
            "timer_mode": timer_info["mode"],
            "timer_active": timer_info["active"],
            "timer_next": timer_info["next"],
            "timer_last": timer_info["last"],
            "timer_status": timer_info["status"],
            # NEW: Safeguards rich export metrics (default flywheel safety)
            "rich_export_success_rate": rich_sr,
            "rich_export_error_rate": rich_err_rate,
            "rich_export_consecutive_failures": rich_consec,
            "rich_export_last_success": rich_last_succ,
            "rich_export_total_attempts": rich_total,
            "flywheel_degraded": degraded,
            "flywheel_degraded_reason": degraded_reason,
            "flywheel_safeguard_active": bool(flywheel_safeguard_msg),
        }
        (state_dir / "watchdog_flywheel_status.json").write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )

        # Rich log line (always cheap) + dedicated flywheel health section
        timer_str = ""
        if timer_info["mode"]:
            timer_str = f" timer={timer_info['status']}({timer_info['mode']}) next={timer_info['next'] or 'n/a'}"
        rich_str = ""
        if rich_total or rich_sr is not None or rich_consec:
            rich_str = f" rich_sr={rich_sr} err_rate={rich_err_rate} consec_fails={rich_consec} last_succ={str(rich_last_succ)[:16] if rich_last_succ else 'n/a'} degraded={degraded}"
        if (
            last_hour
            or high_lv
            or last_ab_age is not None
            or timer_info["mode"]
            or rich_str
        ):
            log(
                f"🌀 Flywheel health: last_hour={last_hour} high_lv={high_lv} last_ab_age_min={last_ab_age}{timer_str}{rich_str} (continuous autonomy + timer active + safeguards)"
            )
        if flywheel_safeguard_msg:
            # explicit section for operators
            log(f"🛡️ Flywheel Safeguards: {flywheel_safeguard_msg}")
    except Exception as _e:
        # Never impact watchdog core loops
        pass


# === Auto-review sweep (подбирает задачи, застрявшие в review) ===
_review_cycle_counter = 0


def auto_review_stale():
    """Подбирает задачи застрявшие в review."""
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
    except Exception as e:
        log(f"⚠️ Auto-review sweep failed: {e}")


def main():
    log(
        "🚀 Запуск AgentForge Watchdog + Guardian (с учётом новой маршрутизации 2026-06)"
    )
    while True:
        try:
            # Flywheel autonomy health (new in continuous wave — polled every 10s, cheap)
            _flywheel_health_report()

            # 1. Зацикливания (Watchdog)
            tasks = get_active_tasks()
            for task in tasks:
                task_id = task["id"]
                log_path = os.path.join(LOG_DIR, f"grok_{task_id}.log")

                reason = analyze_log_for_loops(log_path)
                if reason:
                    log(
                        f"🚨 Обнаружена аномалия в {task_id}: {reason}. Принимаю меры..."
                    )
                    killed = kill_task_process(task_id)
                    mark_task_failed(task_id, reason)
                    if killed:
                        log(f"💀 Процессы задачи {task_id} убиты.")

            # 2. Самоисцеление (Guardian)
            guardian_loop()

            # 3. Подбор застрявших review-задач (sweep каждые ~60 сек)
            auto_review_stale()

        except urllib.error.URLError as e:
            # Exponential backoff при недоступности gateway
            if not hasattr(main, "_backoff"):
                main._backoff = POLL_INTERVAL
            main._backoff = min(main._backoff * 2, 120)
            log(f"⚠️ Gateway недоступен: {e} (retry через {main._backoff}s)")
            time.sleep(main._backoff)
            continue
        except Exception as e:
            log(f"⚠️ Глобальная ошибка: {e}")

        # Сброс backoff при успешном цикле
        if hasattr(main, "_backoff"):
            main._backoff = POLL_INTERVAL
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
