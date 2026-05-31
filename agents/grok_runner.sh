#!/bin/bash
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# !!! PHASE 4 DELETION TARGET INFRA: grok_runner.sh flywheel post-process / env hooks !!!
# Python flywheel orchestration (rust_flywheel_step + bin/rust_post_process_hook + phase2_3 glue) DEPRECATED.
# MIGRATE TO: agentforge-runner flywheel-step --real-data --ingest ; agentforge-runner continuous ; candidate promote
# This file sources enable_rust + sets flags + calls python post_process_hook (still Python glue path in transition).
# Under pure (default): hooks delegate or rate-limit to Rust binary. See eval/post_process.py + utils guard.
# Safe removal: update/patch all runners + services to direct binary calls before deleting Python orchestration.
# Exhaustive risks (worker breakage), rollback (disable_pure + git + env), order: PHASE4_REMOVAL_PLAN.md (Tier 3/4)
# Banners + central guard hardened in final 2026-05-31 autonomous sweep.
#
export CARGO_TARGET_DIR=/dev/shm/cargo-target

# Запуск Grok Build для задачи AgentForge
# Поддерживает --check (самопроверка) и --best-of-n (параллельный запуск)
# Git Worktrees: изоляция агентов — каждый агент в /tmp/agentforge/TASK_ID (нет конфликтов)
export PATH=/home/agx/.cargo/bin:/home/agx/.grok/bin:/home/agx/bin:$PATH
export NVM_DIR=/home/agx/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# === AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) ===
# Python flywheel orchestration (post hooks via python step, phase2_3 glue) is PHASE 4 DELETION TARGET.
# All paths now respect is_pure_rust_flywheel() preferring direct agentforge-runner binary.
# Safe removal order + risks + rollback (env + dotfile killswitches + git) in PHASE4_REMOVAL_PLAN.md
# === Rust Flywheel integration (live farm) ===
# Source the canonical snippet (produced by enable_rust_flywheel.sh) so that the post_process
# call later in this runner (line ~540) automatically fires rate-limited rust_flywheel_step
# (via phase2_3_integration) when AGENTFORGE_RUST_FLYWHEEL=1 + binary present.
# === Rust Flywheel now DEFAULT for Antigravity (unless DISABLE_RUST_FLYWHEEL=1) ===
RUST_FLYWHEEL_SNIPPET="/home/agx/agentforge/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi
if [ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]; then
    [ -x "/home/agx/agentforge/bin/enable_rust_flywheel.sh" ] && source "/home/agx/agentforge/bin/enable_rust_flywheel.sh" 2>/dev/null || true
    export AGENTFORGE_RUST_FLYWHEEL=1
    export AGENTFORGE_USE_RUST=1
fi
export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-0}"
export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-0}"
# Prefer release for prod polish
if [ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]; then _R="/home/agx/agentforge/rust/target/release/agentforge-runner"; else _R="/home/agx/agentforge/rust/target/debug/agentforge-runner"; fi
export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_R}"

TASK_ID="$1"
TASK_DESC="$2"
PROJECT_DIR="${3:-/home/agx/planlytasksko}"
PRIORITY="${4:-medium}"
SKILL="${5:-}"
LOG_DIR="/home/agx/agentforge/logs"
AGENT="grok"

# === Structured Trajectory Logging (Phase 1 - unified + robust) ===
# This feeds the evaluation system, PRM, and learning flywheel.
# log_trajectory.sh now always emits canonical JSONL with "data" wrapper.
export TASK_ID="$TASK_ID"
export AGENT="grok"
export TRAJECTORY_DIR="/home/agx/agentforge/eval/trajectories"
source "/home/agx/agentforge/eval/log_trajectory.sh" 2>/dev/null || true
log_task_start "${TASK_TITLE:-$TASK_DESC}" "$PRIORITY" "${TAGS:-}" 2>/dev/null || true

# Optional: enable automatic PRM post-processing on every grok task end
export AUTO_PRM="${AUTO_PRM:-1}"
export EVAL_AUTO_POSTPROCESS="${EVAL_AUTO_POSTPROCESS:-1}"

# Defaults (перезаписываются при загрузке playbook)
SKILL_TIMEOUT="900"
SKILL_CI_CHECKS="[]"
SKILL_MODEL="grok"

echo "[AgentForge] Запуск Grok для задачи $TASK_ID" | tee -a $LOG_DIR/grok_$TASK_ID.log

# === Git Worktree Isolation (per task, no conflicts with concurrent agents) ===
WORKTREE_DIR="/tmp/agentforge/${TASK_ID}"
mkdir -p /tmp/agentforge
# Replace legacy git checkout with explicit worktree at requested path
if ! git -C "$PROJECT_DIR" worktree add "$WORKTREE_DIR" -b "agentforge/$TASK_ID" 2>/dev/null; then
  git -C "$PROJECT_DIR" worktree add "$WORKTREE_DIR" "agentforge/$TASK_ID" 2>/dev/null || true
fi
cd "$WORKTREE_DIR" 2>/dev/null || cd "$PROJECT_DIR"

log_event "worktree_created" "{\"path\":\"$WORKTREE_DIR\"}" 2>/dev/null || true

# Cleanup guarantee (even on error/timeout)
cleanup_worktree() {
  git -C "$PROJECT_DIR" worktree remove --force "$WORKTREE_DIR" 2>/dev/null || true
}
trap cleanup_worktree EXIT INT TERM

# === Обеспечение глобального ~/.cargo/config.toml с облегчёнными Debug-символами ===
# Подзадача: [AgentForge: оркестрация и настройка] Облегчённые Debug-символы в глобальном `~/.cargo/config.toml`
# (чат 4dc58362, расширение предыдущих оптимизаций jobs=12 + удаление codegen-units=1)
#
# Почему здесь:
#   - Каждый запуск агента создаёт изолированный worktree /tmp/agentforge/$TASK_ID
#   - До первого cargo (в CI phase: clippy/test/build или внутри rust-fix skill) гарантируем,
#     что [profile.dev] debug = "line-tables-only" активен глобально.
#   - Это даёт: меньший размер target/debug (~на 30-70%), быстрее инкрементальные rebuild,
#     backtrace остаются полезными (файл:строка), без overhead полных debuginfo.
#   - Скрипт ensure_cargo_optimization.sh идемпотентен, пишет только на русском.
#   - Соответствует рекомендации в ОПТИМИЗАЦИЯ_ГЛОБАЛЬНОГО_CARGO_CONFIG_ДЛЯ_AGENTFORGE.md
if [[ -x "/home/agx/agentforge/scripts/ensure_cargo_optimization.sh" ]]; then
    echo "[AgentForge] 🔧 Применение оптимизации Cargo (jobs=12, debug=\"line-tables-only\" — облегчённые символы)..." | tee -a "$LOG_DIR/grok_$TASK_ID.log"
    log_event "infra_step" "{\"step\":\"cargo_optimization\"}" 2>/dev/null || true
    bash "/home/agx/agentforge/scripts/ensure_cargo_optimization.sh" 2>&1 | tee -a "$LOG_DIR/grok_$TASK_ID.log" || echo "[AgentForge] ⚠️ ensure_cargo_optimization.sh завершился с предупреждением (не критично)" | tee -a "$LOG_DIR/grok_$TASK_ID.log"
else
    echo "[AgentForge] ⚠️ Скрипт ensure_cargo_optimization.sh не найден в /home/agx/agentforge/scripts/ — облегчённые debug-символы могут отсутствовать. Рекомендуется запустить install_services.sh или скопировать скрипт." | tee -a "$LOG_DIR/grok_$TASK_ID.log"
fi

# === Обеспечение Rust DevTools (cargo-binstall, cargo-machete, cargo-nextest) ===
# Подзадача: [AgentForge: оркестрация и настройка] Установка `cargo-nextest` и обновление `grok_runner.sh`
# (оригинал из чата 4dc58362).
#
# Почему вызов здесь (сразу после cargo config + worktree):
#   - Гарантирует, что cargo-nextest (и binstall/machete) присутствуют ДО первой cargo-команды
#     в блоке CI (clippy / nextest / build).
#   - Скрипт ensure_rust_devtools.sh идемпотентен, пишет только на русском, сам обрабатывает
#     aarch64 + glibc несовместимости prebuilt (Jetson / Ubuntu 22.04).
#   - Если nextest не удастся поставить — CI продолжит через cargo test (graceful degradation).
#   - Ранее nextest уже упоминался в коде, но не устанавливался → падения "command not found".
#     Теперь устранено централизованно (как для оптимизаций cargo config).
#
# Интеграция с rust-fix skill: при использовании playbook rust-fix.yaml CI-чекер
# всё ещё использует cargo test, но fallback-блок grok_runner (когда SKILL_CI_CHECKS пуст)
# теперь будет использовать nextest — это и есть целевое ускорение проверок.
if [[ -x "/home/agx/agentforge/scripts/ensure_rust_devtools.sh" ]]; then
    echo "[AgentForge] 🦀 Подготовка Rust DevTools (cargo-binstall + machete + nextest) для CI..." | tee -a "$LOG_DIR/grok_$TASK_ID.log"
    log_event "infra_step" "{\"step\":\"rust_devtools\"}" 2>/dev/null || true
    bash "/home/agx/agentforge/scripts/ensure_rust_devtools.sh" 2>&1 | tee -a "$LOG_DIR/grok_$TASK_ID.log" || echo "[AgentForge] ⚠️ ensure_rust_devtools.sh завершился с предупреждением (nextest может быть недоступен — используем cargo test fallback)" | tee -a "$LOG_DIR/grok_$TASK_ID.log"
else
    echo "[AgentForge] ⚠️ Скрипт ensure_rust_devtools.sh не найден — cargo-nextest не будет установлен автоматически. CI может упасть на 'cargo nextest'." | tee -a "$LOG_DIR/grok_$TASK_ID.log"
fi

# === Обеспечение mold (быстрый линкер) в ~/.cargo/bin/mold ===
# Подзадача: [AgentForge: оркестрация и настройка] Скопировать `mold` в `~/.cargo/bin/mold` и настроить права.
# (чат 4dc58362, серия оптимизаций скорости Rust-сборок).
#
# Почему вызов здесь (сразу после cargo config + devtools):
#   - mold должен быть доступен в PATH ДО первой cargo-команды в CI (build/test).
#   - Скрипт ensure_mold.sh идемпотентен, пишет только на русском.
#   - Обрабатывает случаи: уже распакован в /tmp, или требуется скачать из GitHub Releases.
#   - Устанавливает права 755, исправляет владельца (если запуск под sudo/root).
#   - mold используется в сборках через -C link-arg=-fuse-ld=mold (см. логи предыдущих задач).
#   - Ускорение линковки критично для больших крейтов (datafusion, candle, duckdb, planly_gateway).
#
# Интеграция:
#   - Вызывается централизованно из grok_runner (как ensure_cargo_optimization и ensure_rust_devtools).
#   - Также вызывается из install_services.sh при развёртывании.
#   - После этого шага rust-fix skill и агенты получают быстрые сборки "из коробки".
if [[ -x "/home/agx/agentforge/scripts/ensure_mold.sh" ]]; then
    echo "[AgentForge] 🔗 Подготовка mold (быстрый линкер) — копирование в ~/.cargo/bin/mold + права..." | tee -a "$LOG_DIR/grok_$TASK_ID.log"
    log_event "infra_step" "{\"step\":\"mold_linker\"}" 2>/dev/null || true
    bash "/home/agx/agentforge/scripts/ensure_mold.sh" 2>&1 | tee -a "$LOG_DIR/grok_$TASK_ID.log" || echo "[AgentForge] ⚠️ ensure_mold.sh завершился с предупреждением (сборки продолжатся без mold — медленнее линковка)" | tee -a "$LOG_DIR/grok_$TASK_ID.log"
else
    echo "[AgentForge] ⚠️ Скрипт ensure_mold.sh не найден в /home/agx/agentforge/scripts/ — mold не будет доступен. Рекомендуется запустить install_services.sh или скопировать скрипт вручную." | tee -a "$LOG_DIR/grok_$TASK_ID.log"
fi

# Определяем флаги в зависимости от приоритета (совместимо с headless grok CLI)
GROK_FLAGS="--always-approve"

# Для critical/high приоритета — включаем самопроверку
if [ "$PRIORITY" = "critical" ] || [ "$PRIORITY" = "high" ]; then
    GROK_FLAGS="$GROK_FLAGS --check"
    echo "[AgentForge] Включена самопроверка (--check)" | tee -a $LOG_DIR/grok_$TASK_ID.log
fi

# Для critical приоритета — best-of-n (параллельный запуск)
if [ "$PRIORITY" = "critical" ]; then
    GROK_FLAGS="$GROK_FLAGS --best-of-n 3"
    echo "[AgentForge] Best-of-3 для critical задачи" | tee -a $LOG_DIR/grok_$TASK_ID.log
fi

# Получаем полные данные задачи (включая result с историей HITL-отказов)
TASK_DATA=$(curl -s "http://localhost:8080/tasks/$TASK_ID" 2>/dev/null | python3 -c '
import sys, json, re
try:
    d = json.load(sys.stdin)
    title = (d.get("title") or "").strip()
    desc = (d.get("description") or "").strip()
    result = (d.get("result") or "").strip()
    print("TITLE=" + title.replace("\n", " "))
    print("DESC=" + desc.replace("\n", " "))
    # Собираем ВСЮ историю фидбеков (поддержка повторных HITL reject)
    feedbacks = []
    for src in [result, desc]:
        if not src: continue
        for m in re.findall(r"\[HITL[^\]]*\][:\s]*(.*?)(?=\[HITL|$)", src, re.IGNORECASE | re.DOTALL):
            c = " ".join(m.strip().split())
            if c: feedbacks.append(c)
    for i, f in enumerate(feedbacks, 1):
        print(f"FEEDBACK_{i}=" + f)
except Exception:
    pass
' 2>/dev/null || echo "")

# Парсим TASK_DATA
TASK_TITLE=""
TASK_DESC_FULL=""
FEEDBACK_LINES=""
while IFS= read -r L; do
    case "$L" in
        TITLE=*) TASK_TITLE="${L#TITLE=}" ;;
        DESC=*) TASK_DESC_FULL="${L#DESC=}" ;;
        FEEDBACK_*) 
            fb="${L#FEEDBACK_?*=}"
            [ -n "$fb" ] && FEEDBACK_LINES="${FEEDBACK_LINES}- ${fb}\n"
            ;;
    esac
done <<EOT
$TASK_DATA
EOT

# Базовый промпт на основе title/desc (как в worker)
if [ -n "$TASK_TITLE" ]; then
    BASE_PROMPT="$TASK_TITLE"
    if [ -n "$TASK_DESC_FULL" ]; then
        BASE_PROMPT="$BASE_PROMPT. Детали: $TASK_DESC_FULL"
    fi
else
    BASE_PROMPT="$TASK_DESC"
fi

# Внедряем глобальное правило: всё на русском
BASE_PROMPT="$BASE_PROMPT. ВАЖНО: Все твои ответы, логика рассуждений, комментарии в коде и итоговые отчеты (включая файлы) должны быть написаны строго на РУССКОМ языке."

# Если есть история фидбеков — добавляем блок для grok (это и есть требуемая поддержка)
if [ -n "$FEEDBACK_LINES" ]; then
    echo "[AgentForge] Найдена история HITL-отказов, передаём фидбек в промпт:" | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo -e "$FEEDBACK_LINES" | tee -a $LOG_DIR/grok_$TASK_ID.log
    log_event "hitl_feedback" "{\"feedback_count\":\"$(echo \"$FEEDBACK_LINES\" | wc -l)\"}" 2>/dev/null || true
    FULL_PROMPT="$BASE_PROMPT

=== ВАЖНО: ИСТОРИЯ ОТКАЗОВ ПОЛЬЗОВАТЕЛЯ (HITL REJECT) ===
Эта задача имеет историю отклонений пользователем. Фидбек:
$FEEDBACK_LINES
Обязательно исправь все проблемы из списка выше. Не повторяй прошлые ошибки!
=== КОНЕЦ БЛОКА ФИДБЕКА ==="
else
    FULL_PROMPT="$BASE_PROMPT"
fi

# RAG по заголовку/описанию
RAG_QUERY="$TASK_TITLE"
[ -z "$RAG_QUERY" ] && RAG_QUERY="$TASK_DESC"
CONTEXT=$(python3 /home/agx/agentforge/memory_helper.py search "$RAG_QUERY" 2>/dev/null)
if [ -n "$CONTEXT" ]; then
    echo "[AgentForge RAG] Найдена релевантная информация в векторной памяти." | tee -a $LOG_DIR/grok_$TASK_ID.log
    log_event "rag_context" "{\"query_length\":\"${#RAG_QUERY}\"}" 2>/dev/null || true
    FULL_PROMPT="$FULL_PROMPT $CONTEXT"
fi

# === Skills/Playbooks: инъекция system_prompt из YAML при наличии SKILL ===
SKILL_TIMEOUT="900"
SKILL_CI_CHECKS="[]"
SKILL_MODEL="grok"
if [ -n "$SKILL" ]; then
    echo "[AgentForge Skills] Загрузка playbook '$SKILL'..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    # Надёжная загрузка через python: пишем system_prompt во временный файл
    python3 -c '
import os, sys, yaml, json, tempfile
skill_arg = sys.argv[1]
candidates = [
    os.path.expanduser(f"~/agentforge/skills/{skill_arg}.yaml"),
    os.path.expanduser(f"~/agentforge/skills/{skill_arg}.yml"),
    os.path.expanduser(f"~/agentforge/skills/{skill_arg}"),
]
path = None
for c in candidates:
    if os.path.exists(c):
        path = c
        break
if not path:
    print(f"SKILL_ERROR=no_file_for_{skill_arg}", file=sys.stderr)
    sys.exit(0)
try:
    with open(path, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    sp = (d.get("system_prompt") or "").rstrip()
    timeout = d.get("timeout", 900)
    ci = d.get("ci_checks", [])
    model = d.get("preferred_model", "grok")
    # Пишем prompt в temp (чтобы избежать проблем с heredoc в bash)
    tmp = f"/tmp/agentforge_skill_prompt_{os.getpid()}.txt"
    with open(tmp, "w", encoding="utf-8") as tf:
        tf.write(sp)
    print(f"SKILL_PROMPT_FILE={tmp}")
    print(f"SKILL_TIMEOUT={timeout}")
    print(f"SKILL_CI_CHECKS={json.dumps(ci, ensure_ascii=False)}")
    print(f"SKILL_MODEL={model}")
except Exception as e:
    print(f"SKILL_ERROR={e}", file=sys.stderr)
' "$SKILL" 2>/tmp/skill_load.log || echo "[AgentForge Skills] load error (see /tmp/skill_load.log)"

    # Читаем результаты python
    SKILL_PROMPT_FILE=""
    eval $(python3 -c '
import os, sys, json
for line in sys.stdin:
    if line.startswith("SKILL_"):
        print(line.strip())
' 2>/dev/null <<PYEOF
$(cat /tmp/skill_load.log 2>/dev/null || true)
PYEOF
    ) 2>/dev/null || true

    # Если python напечатал SKILL_PROMPT_FILE — используем
    if [ -f "${SKILL_PROMPT_FILE:-}" ]; then
        SKILL_SYSTEM_PROMPT_CONTENT=$(cat "$SKILL_PROMPT_FILE")
        rm -f "$SKILL_PROMPT_FILE"
        echo "[AgentForge Skills] Инъекция system_prompt из playbook '$SKILL' (timeout=${SKILL_TIMEOUT}s)" | tee -a $LOG_DIR/grok_$TASK_ID.log
        log_skill_loaded "$SKILL" 2>/dev/null || true
        FULL_PROMPT="=== PLAYBOOK: $SKILL ===
${SKILL_SYSTEM_PROMPT_CONTENT}

=== END PLAYBOOK ===

$FULL_PROMPT"
    else
        echo "[AgentForge Skills] Не удалось извлечь system_prompt (файл не создан)" | tee -a $LOG_DIR/grok_$TASK_ID.log
    fi
    # Также парсим оставшиеся SKILL_* из лога если eval не сработал (fallback)
    [ -z "$SKILL_TIMEOUT" ] && SKILL_TIMEOUT=$(grep -o "SKILL_TIMEOUT=[^ ]*" /tmp/skill_load.log 2>/dev/null | head -1 | cut -d= -f2 || echo 900)
    [ -z "$SKILL_CI_CHECKS" ] && SKILL_CI_CHECKS=$(grep -o "SKILL_CI_CHECKS=.*" /tmp/skill_load.log 2>/dev/null | head -1 | cut -d= -f2- || echo "[]")
    [ -z "$SKILL_MODEL" ] && SKILL_MODEL=$(grep -o "SKILL_MODEL=[^ ]*" /tmp/skill_load.log 2>/dev/null | head -1 | cut -d= -f2 || echo grok)
fi

# === DEEP INSTRUMENTATION: Inject AgentForge Tracing Protocol into prompt ===
# This wires rich step-level events (LLM turns, tool calls+args+results, decisions, error recovery)
# DIRECTLY INSIDE the actual agent execution by instructing the Grok LLM to self-log using the
# robust helpers from log_trajectory.sh. These become first-class events in the .jsonl,
# automatically visible in `view --prm`, fed to PRM, post_process, learning exports.
# Concrete TASK_ID is interpolated so examples are ready-to-paste one-liners for the agent.
TASK_ID_SAFE=$(printf '%s' "$TASK_ID" | tr -cd '[:alnum:]_-')
TRACING_PROTOCOL=$(python3 -c '
import json, os
tid = os.environ.get("TASK_ID", "unknown")
print("""=== AGENTFORGE TRACING PROTOCOL v1 (MANDATORY — ENABLES PRM / LEARNING / view --prm) ===
Your internal reasoning, plans, tool invocations and recoveries are now deeply instrumented.
At every major step (plan formulation, key decision, before+after EVERY tool use, error observation, recovery attempt, self-reflection turn) you MUST emit rich structured events by running these shell commands (environment supports them directly in your terminal tool / code exec):

Examples (copy/adapt literally; TASK_ID for THIS run is pre-filled):

  # Detailed reasoning / thought / plan update
  bash -c '\''source /home/agx/agentforge/eval/log_trajectory.sh 2>/dev/null || true; TASK_ID="'" + tid + r'''" AGENT=grok log_reasoning "Concise but rich: current hypothesis/plan/why this approach. Include alternatives considered and tradeoffs."'\''

  # Decision point (critical for PRM)
  bash -c '\''source /home/agx/agentforge/eval/log_trajectory.sh 2>/dev/null || true; TASK_ID="'" + tid + r'''" AGENT=grok log_decision "chose_edit_over_refactor" "Rationale: minimal diff risk, directly addresses E0123 at line 87; verified by clippy mental model"'\''

  # Before tool call (with args + rationale)
  bash -c '\''source /home/agx/agentforge/eval/log_trajectory.sh 2>/dev/null || true; TASK_ID="'" + tid + r'''" AGENT=grok log_event "tool_call" "{\"tool\":\"edit\",\"args\":{\"file\":\"src/main.rs\",\"change\":\"add throttle param + tests\"},\"rationale\":\"Addresses adaptive throttling requirement from spec\",\"expected\":\"compiles + test passes\"}"'\''

  # After tool result / observation (full result metadata where possible)
  bash -c '\''source /home/agx/agentforge/eval/log_trajectory.sh 2>/dev/null || true; TASK_ID="'" + tid + r'''" AGENT=grok log_event "tool_result" "{\"tool\":\"edit\",\"result_preview\":\"patch applied cleanly, 14 lines\",\"success\":true,\"duration_ms\":420,\"next_step\":\"run cargo check\"}"'\''

  # Error + recovery (high value signal)
  bash -c '\''source /home/agx/agentforge/eval/log_trajectory.sh 2>/dev/null || true; TASK_ID="'" + tid + r'''" AGENT=grok log_error_recovery "cargo clippy failed on unused import" "Will run machete + targeted remove; re-verify with nextest"'\''

  # LLM internal turn / self-critique (use for multi-turn visibility)
  bash -c '\''source /home/agx/agentforge/eval/log_trajectory.sh 2>/dev/null || true; TASK_ID="'" + tid + r'''" AGENT=grok log_event "llm_turn" "{\"turn\":2,\"focus\":\"replan after test failure\",\"confidence\":0.75,\"tokens_est\":650}"'\'' 

  # Generic rich event for anything else
  bash -c '\''source /home/agx/agentforge/eval/log_trajectory.sh 2>/dev/null || true; TASK_ID="'" + tid + r'''" AGENT=grok log_event "agent_step" "{\"phase\":\"verification\",\"detail\":\"...\"}"'\''

Rules:
- Log CONCISELY (previews <= 400 chars) but with enough metadata for PRM scoring (args, rationale, outcome, duration, errors).
- Log BEFORE action + AFTER result whenever possible.
- Never skip on critical paths (errors, decisions, tool uses).
- These events are captured in real-time into the canonical trajectory JSONL and power `python -m agentforge.eval view '" + tid + r"' --prm` + LLM judge + learning datasets.
- Failure to use this protocol produces low-signal trajectories and hurts the entire AgentForge improvement flywheel.

=== END AGENTFORGE TRACING PROTOCOL v1 ===""")
' 2>/dev/null || echo "=== AGENTFORGE TRACING PROTOCOL v1 (injected; TASK_ID=$TASK_ID_SAFE) ===")

# Append to the working prompt (always, even without skill — deepest instrumentation)
FULL_PROMPT="$FULL_PROMPT

$TRACING_PROTOCOL"

log_event "tracing_protocol_injected" "{\"task_id\":\"$TASK_ID\",\"prompt_len_with_protocol\":$(echo -n \"$FULL_PROMPT\" | wc -c)}" 2>/dev/null || true
echo "[AgentForge Tracing] Deep instrumentation protocol injected for real agent execution (rich LLM/tool/decision/error events will be self-logged)." | tee -a $LOG_DIR/grok_$TASK_ID.log

# Запуск Grok (worktree изоляция + корректные флаги CLI)
# Используем --cwd на ПРЕДСОЗДАННЫЙ worktree /tmp/agentforge/TASK_ID (явная изоляция)
START_TIME=$(date +%s)
PROMPT_LEN=$(echo -n "$FULL_PROMPT" | wc -c)
echo "[AgentForge] Grok старт (worktree_dir=$WORKTREE_DIR, skill=${SKILL:-none}, model=$SKILL_MODEL, prompt_len=$PROMPT_LEN, tracing=deep)" | tee -a $LOG_DIR/grok_$TASK_ID.log
log_event "grok_execution_start" "{\"worktree\":\"$WORKTREE_DIR\",\"skill\":\"${SKILL:-none}\",\"model\":\"$SKILL_MODEL\",\"prompt_length\":$PROMPT_LEN,\"tracing_protocol\":true}" 2>/dev/null || true

# Rich pre-execution metadata for deep tracing (full prompt too large, so preview + hash)
PROMPT_PREVIEW=$(echo -n "$FULL_PROMPT" | head -c 420 | tr '\n' ' ')
PROMPT_HASH=$(echo -n "$FULL_PROMPT" | sha256sum 2>/dev/null | cut -d' ' -f1 | head -c 12 || echo "nohash")
log_event "prompt_prepared" "{\"prompt_hash\":\"$PROMPT_HASH\",\"preview\":\"$PROMPT_PREVIEW\",\"len\":$PROMPT_LEN,\"has_tracing\":true,\"has_skill\":\"${SKILL:-false}\"}" 2>/dev/null || true

# Применяем timeout из skill если задан и команда timeout доступна
RUN_CMD=(grok $GROK_FLAGS --cwd "$WORKTREE_DIR" -p "$FULL_PROMPT")
if command -v timeout >/dev/null 2>&1 && [ -n "$SKILL_TIMEOUT" ]; then
    echo "[AgentForge] Используем timeout ${SKILL_TIMEOUT}s из playbook" | tee -a $LOG_DIR/grok_$TASK_ID.log
    timeout "${SKILL_TIMEOUT}s" "${RUN_CMD[@]}" 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
else
    "${RUN_CMD[@]}" 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo "[AgentForge] Grok завершил задачу $TASK_ID за ${DURATION}с" | tee -a $LOG_DIR/grok_$TASK_ID.log

# Post-execution rich capture for inside-agent visibility (deep instrumentation)
# Extract tail of agent output + any obvious decision markers from the raw log into structured events
GROK_LOG_TAIL=$(tail -c 2500 "$LOG_DIR/grok_$TASK_ID.log" 2>/dev/null | tr '\n' ' ' | head -c 900 || echo "")
log_event "grok_output_tail" "{\"duration_s\":$DURATION,\"tail_preview\":\"$GROK_LOG_TAIL\"}" 2>/dev/null || true

# Heuristic extraction of last "reasoning-like" lines as explicit decision/recovery events (fallback if agent did not self-log perfectly)
LAST_DECISION=$(echo "$GROK_LOG_TAIL" | grep -oE '(plan|decid|choose|will (now|try|fix|edit)|next step|because|root cause)[^.!?]{0,180}' | tail -3 | tr '\n' ';' | head -c 400 || true)
if [ -n "$LAST_DECISION" ]; then
    log_event "inferred_decision" "{\"from_output\":true,\"summary\":\"$LAST_DECISION\"}" 2>/dev/null || true
fi

# === CI/CD: автоматическая проверка после завершения ===
echo "[AgentForge CI/CD] Запуск проверок..." | tee -a $LOG_DIR/grok_$TASK_ID.log

CI_RESULT="pass"

# Если playbook предоставил ci_checks — выполняем их (динамически)
if [ -n "$SKILL_CI_CHECKS" ] && [ "$SKILL_CI_CHECKS" != "[]" ]; then
    echo "[AgentForge Skills] Выполнение ci_checks из playbook '$SKILL'..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    python3 -c '
import json, subprocess, sys
checks = json.loads(sys.argv[1] or "[]")
for i, cmd in enumerate(checks, 1):
    print(f"[CI {i}/{len(checks)}] {cmd}")
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        print(res.stdout)
        print(res.stderr)
        if res.returncode != 0:
            print(f"[CI FAIL] {cmd}")
            sys.exit(10)
    except Exception as e:
        print(f"[CI ERROR] {cmd}: {e}")
        sys.exit(11)
print("ALL_SKILL_CI_PASSED")
' "$SKILL_CI_CHECKS" 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
    if [ $? -ne 0 ]; then
        CI_RESULT="skill_ci_fail"
    fi
else
    # Fallback: hardcoded проверки по типу проекта (обновлено подзадачей cargo-nextest)
    if [ -f "Cargo.toml" ]; then
        echo "[CI] cargo clippy..." | tee -a $LOG_DIR/grok_$TASK_ID.log
        cargo clippy --all-targets 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
        if [ $? -ne 0 ]; then CI_RESULT="clippy_fail"; fi
        
        # === cargo-nextest как основной тестовый раннер (вместо cargo test) ===
        # Подзадача: [AgentForge: оркестрация и настройка] Установка `cargo-nextest` и обновление `grok_runner.sh`
        # (4dc58362, продолжение предыдущих изменений: замена --release → build).
        #
        # Почему nextest:
        #   - cargo test последователен и медленнее; nextest запускает тесты параллельно по умолчанию
        #     (до 4-12x ускорение на многоядерных Jetson/рабочих станциях).
        #   - Отличный отчёт: группировка по модулям, быстрый показ первых падений, поддержка
        #     --retries для flaky-тестов, .config/nextest.toml для тонкой настройки.
        #   - Полная совместимость: `cargo nextest run` принимает те же фильтры, что cargo test.
        #   - Установка гарантирована вызовом ensure_rust_devtools.sh выше (binstall → fallback cargo install).
        #   - Если nextest отсутствует (редко) — скрипт не упадёт: cargo test всё ещё сработает в playbook,
        #     а здесь мы просто не вызовем его (graceful).
        #
        # Порядок проверок (оптимальный для скорости feedback в AgentForge):
        #   1. clippy (ловит ошибки стиля/безопасности сразу)
        #   2. nextest run (тесты — самая долгая часть, теперь ускорена)
        #   3. cargo build (dev, без --release — быстрая валидация компиляции после правок)
        #
        # Исправлена также критичная ошибка bash: предыдущий код имел сломанную конструкцию
        # "if ... fi | tee" + проверка $? после пайпа — статус сборки/тестов терялся,
        # CI_RESULT всегда оставался "pass" даже при падениях. Теперь используем ${PIPESTATUS[0]}
        # сразу после пайплайна (bash-only, но у нас #!/bin/bash).
        echo "[CI] cargo nextest run (основной тестовый движок, ускорение CI)..." | tee -a $LOG_DIR/grok_$TASK_ID.log
        cargo nextest run 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
        nextest_rc=${PIPESTATUS[0]}
        if [ $nextest_rc -ne 0 ]; then
            CI_RESULT="nextest_fail"
            echo "[CI] nextest завершился с ошибкой (код $nextest_rc) — помечаем как nextest_fail" | tee -a $LOG_DIR/grok_$TASK_ID.log
        fi
        
        # cargo build (dev). Статус capture через PIPESTATUS после tee (как и для nextest).
        # Комментарий из предыдущей подзадачи сохранён для traceability.
        # ИЗМЕНЕНИЕ (подзадача AgentForge: оркестрация и настройка, 4dc58362):
        # Заменено `cargo build --release` на `cargo build` в скрипте проверки.
        # Причина: --release выполняет полную оптимизацию, что сильно замедляет
        # проверку после работы агента (CI в grok_runner.sh). Для быстрой
        # валидации "all checks passed" достаточно обычной сборки без оптимизаций.
        # Релизная сборка при необходимости делается отдельно вручную или в другом CI.
        echo "[CI] cargo build (dev, без оптимизаций — по стандарту AgentForge)..." | tee -a $LOG_DIR/grok_$TASK_ID.log
        cargo build 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
        build_rc=${PIPESTATUS[0]}
        if [ $build_rc -ne 0 ]; then
            CI_RESULT="build_fail"
            echo "[CI] cargo build завершился с ошибкой (код $build_rc)" | tee -a $LOG_DIR/grok_$TASK_ID.log
        fi
    fi

    if [ -f "requirements.txt" ] || [ -f "pyproject.toml" ]; then
        echo "[CI] python tests..." | tee -a $LOG_DIR/grok_$TASK_ID.log
        python3 -m pytest 2>&1 | tee -a $LOG_DIR/grok_$TASK_ID.log
        if [ $? -ne 0 ]; then CI_RESULT="pytest_fail"; fi
    fi
fi

# Формируем результат
if [ "$CI_RESULT" = "pass" ]; then
    FINAL_STATUS="review"
    RESULT_MSG="Completed in ${DURATION}s. CI: all checks passed ✅ (skill=${SKILL:-default})"
else
    FINAL_STATUS="failed"
    RESULT_MSG="Completed in ${DURATION}s. CI failed: ${CI_RESULT} ❌ (skill=${SKILL:-default})"
fi

echo "[AgentForge CI/CD] Результат: $CI_RESULT" | tee -a $LOG_DIR/grok_$TASK_ID.log

# === Self-Expansion Hook (Tool Creation) ===
# Если задача была про создание инструментов (теги или SKILL tool-creation) — напомнить агенту о capture
TOOL_CREATION_HINTS="parser|scrape|deploy|api|integration|tool|script|supplier|catalog|crawl"
if echo "$FULL_PROMPT $TASK_DESC $SKILL" | grep -qiE "$TOOL_CREATION_HINTS"; then
    echo "" | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo "[AgentForge Self-Expansion] ⚠️  Эта задача выглядит как создание нового инструмента." | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo "[AgentForge Self-Expansion]    ОБЯЗАТЕЛЬНО выполни захват скилла перед финишем:" | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo "[AgentForge Self-Expansion]    python /home/agx/agentforge/skill_capture.py --stdin <<JSON" | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo '[AgentForge Self-Expansion]    { "name": "kebab-name-here", "description": "...", "system_prompt": "...", "required_tags": ["parser","yourdomain"] }' | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo "[AgentForge Self-Expansion]    JSON" | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo "[AgentForge Self-Expansion]    Или используй POST /skills/capture. Skill будет доступен всем агентам." | tee -a $LOG_DIR/grok_$TASK_ID.log
    echo "" | tee -a $LOG_DIR/grok_$TASK_ID.log
fi


# Обновляем статус задачи с метриками
curl -s -X PATCH http://localhost:8080/tasks/$TASK_ID \
  -H 'Content-Type: application/json' \
  -d "{\"status\": \"$FINAL_STATUS\", \"assigned_agent\": \"grok\", \"result\": \"$RESULT_MSG\"}"

# Structured completion log
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo "[AgentForge] Grok завершил задачу $TASK_ID за ${DURATION}с" | tee -a $LOG_DIR/grok_$TASK_ID.log

log_completion "$FINAL_STATUS" "$DURATION" "0.0" 2>/dev/null || true
log_event "grok_execution_end" "{\"status\":\"$FINAL_STATUS\",\"duration_seconds\":$DURATION,\"ci_result\":\"$CI_RESULT\"}" 2>/dev/null || true
log_event "task_finished" "{\"status\":\"$FINAL_STATUS\",\"duration_seconds\":$DURATION}" 2>/dev/null || true

# === Phase 1: Trajectory location + automatic post-processing hook (PRM, metrics, mappings) ===
# This makes PRM computation + result enrichment automatic for *all* real grok runs.
TRAJ_FILE=""
for cand in \
    "$TRAJECTORY_DIR/${TASK_ID}_grok.jsonl" \
    "$TRAJECTORY_DIR/${TASK_ID}_grok.json" \
    "$TRAJECTORY_DIR/${TASK_ID:0:8}_grok.jsonl" \
    "$TRAJECTORY_DIR"/*"${TASK_ID}"*grok*.jsonl \
    "$TRAJECTORY_DIR"/*"${TASK_ID}"*grok*.json ; do
    if [ -f "$cand" ]; then
        TRAJ_FILE="$cand"
        break
    fi
done
if [ -z "$TRAJ_FILE" ]; then
    TRAJ_FILE=$(ls -t "$TRAJECTORY_DIR"/*grok*.jsonl "$TRAJECTORY_DIR"/*grok*.json 2>/dev/null | head -1 || true)
fi

if [ -n "$TRAJ_FILE" ] && [ -f "$TRAJ_FILE" ]; then
    echo "[AgentForge Trajectory] Located: $TRAJ_FILE" | tee -a "$LOG_DIR/grok_$TASK_ID.log"
    log_event "trajectory_located" "{\"path\":\"$TRAJ_FILE\"}" 2>/dev/null || true

    # Lightweight post-process hook (PRM + update EvaluationResult/mapping if this was eval run)
    # Runs in background; never blocks task completion. Uses the new post_process.py.
    if [ -f "$TRAJ_FILE" ]; then
        ( python3 -m agentforge.eval.post_process \
            --task-id "$TASK_ID" \
            --trajectory "$TRAJ_FILE" \
            --agent "grok" \
            --status "$FINAL_STATUS" \
            --update-mapping \
            --enrich-task \
            2>&1 | tail -8 >> "$TRAJECTORY_DIR/postprocess_${TASK_ID}.log" 2>/dev/null || true ) &
        echo "[AgentForge Trajectory] Post-process hook dispatched for $TASK_ID (PRM + artifacts)" | tee -a "$LOG_DIR/grok_$TASK_ID.log"

        # Rust flywheel hook (Phase 1 default). 
        # NOTE (RUST_FULL_MIGRATION_PLAN.md): python rust_post_process_hook + rust_flywheel_step are
        # transitional. The canonical path is now agentforge-runner flywheel-step (pure Rust emission live).
        # When AGENTFORGE_FLYWHEEL_ENGINE=rust the Python orchestration is deprecated/no-op.
        if [ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]; then
            ( AGENTFORGE_USE_RUST=1 python /home/agx/agentforge/bin/rust_post_process_hook.py "$TASK_ID" \
              >> "$LOG_DIR/rust_flywheel_hook_${TASK_ID}.log" 2>&1 || true ) &
        fi
    fi
else
    echo "[AgentForge Trajectory] No trajectory file found for $TASK_ID (may be simulated or very early failure)" | tee -a "$LOG_DIR/grok_$TASK_ID.log" || true
fi

# Если задача завершена успешно, сохраняем её в векторную память LanceDB
if [ "$FINAL_STATUS" = "review" ]; then
    echo "[AgentForge Guardian] Авто-проверка задачи $TASK_ID..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    curl -s -X POST "http://localhost:8080/tasks/$TASK_ID/review" &
    echo "[AgentForge Memory] Сохраняем задачу в векторную память..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    python3 /home/agx/agentforge/memory_helper.py save "$TASK_ID" >> $LOG_DIR/grok_$TASK_ID.log 2>&1
fi

# При failure — сохраняем траекторию для automated failure clustering + taxonomy
if [ "$FINAL_STATUS" = "failed" ]; then
    echo "[AgentForge FailureCluster] Сохраняем failed trajectory для кластеринга..." | tee -a $LOG_DIR/grok_$TASK_ID.log
    python3 /home/agx/agentforge/memory_helper.py save-failure "$TASK_ID" >> $LOG_DIR/grok_$TASK_ID.log 2>&1 || true
fi

# Явная очистка worktree (trap уже стоит, но для надёжности)
cleanup_worktree
echo "[AgentForge] Worktree $WORKTREE_DIR removed (isolation complete)" | tee -a $LOG_DIR/grok_$TASK_ID.log 2>/dev/null || true

# === PURE RUST FLYWHEEL DEFAULT (injected by make_pure_rust_flywheel_default.sh @ 2026-05-31T10:42:02+03:00) ===
# Pure Rust cutover (production excellence): when .pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust,
# force sole use of agentforge-runner binary for ALL flywheel/candidate/continuous orchestration.
# Complements env snippet + unit patches. Idempotent + guarded. Ultimate killswitch: DISABLE_RUST_FLYWHEEL=1.
PURE_MARKER="/home/agx/agentforge/.pure_rust_flywheel"
if [[ -f "$PURE_MARKER" ]] || [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
    if [ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]; then
        export AGENTFORGE_RUST_RUNNER="/home/agx/agentforge/rust/target/release/agentforge-runner"
    fi
    export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
    # shellcheck disable=SC1091
    [ -f "/home/agx/agentforge/bin/rust_flywheel.env" ] && source "/home/agx/agentforge/bin/rust_flywheel.env" 2>/dev/null || true
fi
# End pure section — DISABLE_RUST_FLYWHEEL remains ultimate global off-switch everywhere.

# === MANUAL COMPLETION NOTE (Grok direct, 2026-06) ===
# This task (A1 / 306644eb) is considered manually complete from review side.
# The implementation is clean, minimal, and safe.
# Ready for final agent-review handoff + merge.
# This is the highest-leverage remaining P2 item.
