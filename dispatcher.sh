#!/bin/bash
# AgentForge Dispatcher - launches tasks via appropriate agent
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# !!! Python flywheel orchestration paths (via runners/hooks) deprecated — Phase 4 target !!!
# Python orchestration (rust_flywheel_step + continuous + pending + improver etc) fully deprecated.
# Prefer: agentforge-runner flywheel-step / continuous / candidate [list|promote]
# Guard: is_pure_rust_flywheel() from learning/utils.py (respects .disable_pure_rust_flywheel + env + dotfiles).
# See PHASE4_REMOVAL_PLAN.md (Tier 3/4 for sh/hooks/services, safe order, risks, instant rollback via env+dotfile+git).
# Non-breaking during transition; Python only executes on explicit !pure rollback.
#
# Phase 1 (RUST_FULL_MIGRATION_PLAN.md): Pure Rust flywheel (agentforge-runner flywheel-step)
# is the canonical self-improvement engine. Python flywheel orchestration (rust_flywheel_step.py etc)
# is deprecated and short-circuited under default Antigravity (AGENTFORGE_FLYWHEEL_ENGINE=rust).
# After-task hooks in grok_runner now prefer the Rust path when enabled.
# Rollback: DISABLE_RUST_FLYWHEEL=1 or .disable_rust_flywheel file.
#
# PHASE 3 FINAL SWEEP: escalated deprecation banners + stronger is_pure_rust_flywheel() guards
# (central in learning/utils.py now covers marker + .disable_pure + all envs).
# Direct: agentforge-runner flywheel-step / continuous
export PATH=/home/eveselove/.cargo/bin:/home/eveselove/.grok/bin:/home/eveselove/bin:$PATH

# === Rust Flywheel propagation (for dispatcher-launched runners) ===
# SAFE DEFAULT: full Rust self-improving flywheel is ON for Antigravity tasks.
# Rollback: DISABLE_RUST_FLYWHEEL=1 or /home/eveselove/agentforge/.disable_rust_flywheel
RUST_FLYWHEEL_SNIPPET="/home/eveselove/agentforge/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi
AGENTFORGE_DIR="/home/eveselove/agentforge"
DISABLE_FILE="$AGENTFORGE_DIR/.disable_rust_flywheel"
if [[ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]] && [[ ! -f "$DISABLE_FILE" ]]; then
    # Default ON path — prefer release binary everywhere
    export AGENTFORGE_RUST_FLYWHEEL=1
    export AGENTFORGE_USE_RUST=1
    if [ -x "/home/eveselove/agentforge/rust/target/release/agentforge-runner" ]; then
      _RUST_RUNNER="/home/eveselove/agentforge/rust/target/release/agentforge-runner"
    else
      _RUST_RUNNER="/home/eveselove/agentforge/rust/target/debug/agentforge-runner"
    fi
    export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_RUST_RUNNER}"

    # Source enable snippet (now also respects disable) + helper for extra activation
    [ -x /home/eveselove/agentforge/bin/enable_rust_flywheel.sh ] && source /home/eveselove/agentforge/bin/enable_rust_flywheel.sh 2>/dev/null || true
fi

# Final export: default 1 (unless a disable flag/env took effect above or in sourced snippet)
if [[ "${DISABLE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ -f "$DISABLE_FILE" ]]; then
    export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-0}"
    export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-0}"
else
    export AGENTFORGE_RUST_FLYWHEEL="${AGENTFORGE_RUST_FLYWHEEL:-1}"
    export AGENTFORGE_USE_RUST="${AGENTFORGE_USE_RUST:-1}"
fi

TASK_ID="$1"
AGENT="$2"
DESC="$3"
PRIORITY="${4:-medium}"
SKILL="${5:-}"

# === БЕЗОПАСНОСТЬ: санитизация входных данных ===
# Валидация TASK_ID (только alnum, дефисы, подчёркивания)
if [[ ! "$TASK_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "[AgentForge] ❌ Невалидный TASK_ID: содержит запрещённые символы"
    exit 1
fi

# Сохраняем DESC в файл вместо передачи через shell (защита от injection)
DESC_DIR="/home/eveselove/agentforge/logs/task_desc"
mkdir -p "$DESC_DIR"
DESC_FILE="$DESC_DIR/${TASK_ID}.desc"
printf '%s' "$DESC" > "$DESC_FILE"

# === TMUX-ИЗОЛЯЦИЯ: каждый агент в отдельном терминале ===
TMUX_SESSION="agents"
TASK_SHORT="${TASK_ID:0:8}"
LOG_DIR="/home/eveselove/agentforge/logs"

# Создаём tmux-сессию если не существует
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux new-session -d -s "$TMUX_SESSION" -x 220 -y 50
    echo "[AgentForge] 📺 Создана tmux-сессия '$TMUX_SESSION'"
fi

# Лимиты параллельности по типу агента
MAX_GROK=5
MAX_AGY=3

case $AGENT in
  grok)
    # === ДЕДУПЛИКАЦИЯ: не запускаем если задача уже выполняется ===
    if pgrep -f "grok_runner.sh $TASK_ID" > /dev/null 2>&1; then
        echo "[AgentForge] Task $TASK_ID already running, skipping duplicate dispatch"
        exit 0
    fi
    # Проверяем общее количество grok_runner процессов
    RUNNING_COUNT=$(pgrep -cf "grok_runner.sh" 2>/dev/null || echo 0)
    if [ "$RUNNING_COUNT" -ge "$MAX_GROK" ]; then
        echo "[AgentForge] Too many grok runners ($RUNNING_COUNT/$MAX_GROK), skipping $TASK_ID"
        exit 0
    fi

    # Запуск в отдельном tmux-окне (DESC читается из файла — без injection)
    WINDOW_NAME="grok-${TASK_SHORT}"
    tmux new-window -t "$TMUX_SESSION" -n "$WINDOW_NAME" \
        "DESC=\$(cat '$DESC_FILE' 2>/dev/null); \
         echo '[AgentForge] 🟦 Grok Build → $TASK_ID ($PRIORITY)'; \
         bash /home/eveselove/agentforge/agents/grok_runner.sh '$TASK_ID' \"\$DESC\" '/home/eveselove/planlytasksko' '$PRIORITY' '$SKILL'; \
         echo ''; echo '--- Grok $TASK_SHORT завершён ---'; \
         rm -f '$DESC_FILE'; sleep 10" 2>/dev/null || {
        echo "[AgentForge] ⚠️ tmux fallback — запуск в фоне"
        DESC_SAFE=$(cat "$DESC_FILE" 2>/dev/null)
        bash /home/eveselove/agentforge/agents/grok_runner.sh "$TASK_ID" "$DESC_SAFE" "/home/eveselove/planlytasksko" "$PRIORITY" "$SKILL" &
    }
    echo "[AgentForge] 📺 Grok → tmux окно '$WINDOW_NAME' (${RUNNING_COUNT}/${MAX_GROK} активных)"
    ;;
  agy)
    # Проверяем лимит параллельных AGY
    AGY_RUNNING=$(pgrep -cf "agy_runner.sh" 2>/dev/null || echo 0)
    if [ "$AGY_RUNNING" -ge "$MAX_AGY" ]; then
        echo "[AgentForge] Too many AGY runners ($AGY_RUNNING/$MAX_AGY), skipping $TASK_ID"
        exit 0
    fi

    WINDOW_NAME="agy-${TASK_SHORT}"
    tmux new-window -t "$TMUX_SESSION" -n "$WINDOW_NAME" \
        "DESC=\$(cat '$DESC_FILE' 2>/dev/null); \
         echo '[AgentForge] 🟩 AGY → $TASK_ID'; \
         bash /home/eveselove/agentforge/agents/agy_runner.sh '$TASK_ID' \"\$DESC\"; \
         echo ''; echo '--- AGY $TASK_SHORT завершён ---'; \
         rm -f '$DESC_FILE'; sleep 10" 2>/dev/null || {
        DESC_SAFE=$(cat "$DESC_FILE" 2>/dev/null)
        bash /home/eveselove/agentforge/agents/agy_runner.sh "$TASK_ID" "$DESC_SAFE" &
    }
    echo "[AgentForge] 📺 AGY → tmux окно '$WINDOW_NAME' (${AGY_RUNNING}/${MAX_AGY} активных)"
    ;;
  gemini)
    WINDOW_NAME="gem-${TASK_SHORT}"
    tmux new-window -t "$TMUX_SESSION" -n "$WINDOW_NAME" \
        "DESC=\$(cat '$DESC_FILE' 2>/dev/null); \
         echo '[AgentForge] 🟨 Gemini → $TASK_ID'; \
         bash /home/eveselove/agentforge/agents/gemini_runner.sh '$TASK_ID' \"\$DESC\"; \
         echo ''; echo '--- Gemini $TASK_SHORT завершён ---'; \
         rm -f '$DESC_FILE'; sleep 10" 2>/dev/null || {
        DESC_SAFE=$(cat "$DESC_FILE" 2>/dev/null)
        bash /home/eveselove/agentforge/agents/gemini_runner.sh "$TASK_ID" "$DESC_SAFE" &
    }
    echo "[AgentForge] 📺 Gemini → tmux окно '$WINDOW_NAME'"
    ;;
  antigravity)
    # Antigravity — human-in-the-loop через IDE чат
    echo "[AgentForge] ⚠️  Задача $TASK_ID назначена на Antigravity (требует человеческого/архитектурного внимания)"
    echo "[AgentForge]     Открой Antigravity IDE чат и возьми задачу вручную."

    curl -s -X PATCH "http://127.0.0.1:9090/tasks/$TASK_ID" \
      -H 'Content-Type: application/json' \
      -d "{
        \"status\": \"dispatched\",
        \"assigned_agent\": \"antigravity\",
        \"result\": \"[ROUTING] Задача направлена на Antigravity (human-in-the-loop). Открой Antigravity IDE чат. См. план: AGENTFORGE_ROUTING_AND_EXECUTION_REFACTOR_PLAN.md\"
      }" > /dev/null 2>&1 || true
    ;;
  *)
    echo "[AgentForge] Неизвестный агент: $AGENT"
    exit 1
    ;;
esac

echo "[AgentForge] Задача $TASK_ID отправлена агенту $AGENT (priority=$PRIORITY, skill=${SKILL:-none})"

# === PURE RUST FLYWHEEL DEFAULT (injected by make_pure_rust_flywheel_default.sh @ 2026-05-31T10:42:02+03:00) ===
# Pure Rust cutover (production excellence): when .pure_rust_flywheel or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust,
# force sole use of agentforge-runner binary for ALL flywheel/candidate/continuous orchestration.
# Complements env snippet + unit patches. Idempotent + guarded. Ultimate killswitch: DISABLE_RUST_FLYWHEEL=1.
PURE_MARKER="/home/eveselove/agentforge/.pure_rust_flywheel"
if [[ -f "$PURE_MARKER" ]] || [[ "${AGENTFORGE_PURE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ "${AGENTFORGE_FLYWHEEL_ENGINE:-}" = "rust" ]]; then
    export AGENTFORGE_PURE_RUST_FLYWHEEL=1
    export AGENTFORGE_FLYWHEEL_ENGINE=rust
    if [ -x "/home/eveselove/agentforge/rust/target/release/agentforge-runner" ]; then
        export AGENTFORGE_RUST_RUNNER="/home/eveselove/agentforge/rust/target/release/agentforge-runner"
    fi
    export AGENTFORGE_FLYWHEEL_PROVENANCE="rust-agentforge-runner"
    # shellcheck disable=SC1091
    [ -f "/home/eveselove/agentforge/bin/rust_flywheel.env" ] && source "/home/eveselove/agentforge/bin/rust_flywheel.env" 2>/dev/null || true
fi
# End pure section — DISABLE_RUST_FLYWHEEL remains ultimate global off-switch everywhere.
