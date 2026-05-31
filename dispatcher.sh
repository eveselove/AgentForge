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
# After-task hooks in grok_runner/jules_runner now prefer the Rust path when enabled.
# Rollback: DISABLE_RUST_FLYWHEEL=1 or .disable_rust_flywheel file.
#
# PHASE 3 FINAL SWEEP: escalated deprecation banners + stronger is_pure_rust_flywheel() guards
# (central in learning/utils.py now covers marker + .disable_pure + all envs).
# Direct: agentforge-runner flywheel-step / continuous
export PATH=/home/agx/.cargo/bin:/home/agx/.grok/bin:/home/agx/bin:$PATH

# === Rust Flywheel propagation (for dispatcher-launched runners) ===
# SAFE DEFAULT: full Rust self-improving flywheel is ON for Antigravity tasks.
# Rollback: DISABLE_RUST_FLYWHEEL=1 or /home/agx/agentforge/.disable_rust_flywheel
RUST_FLYWHEEL_SNIPPET="/home/agx/agentforge/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi
AGENTFORGE_DIR="/home/agx/agentforge"
DISABLE_FILE="$AGENTFORGE_DIR/.disable_rust_flywheel"
if [[ "${DISABLE_RUST_FLYWHEEL:-0}" != "1" ]] && [[ ! -f "$DISABLE_FILE" ]]; then
    # Default ON path — prefer release binary everywhere
    export AGENTFORGE_RUST_FLYWHEEL=1
    export AGENTFORGE_USE_RUST=1
    if [ -x "/home/agx/agentforge/rust/target/release/agentforge-runner" ]; then
      _RUST_RUNNER="/home/agx/agentforge/rust/target/release/agentforge-runner"
    else
      _RUST_RUNNER="/home/agx/agentforge/rust/target/debug/agentforge-runner"
    fi
    export AGENTFORGE_RUST_RUNNER="${AGENTFORGE_RUST_RUNNER:-$_RUST_RUNNER}"

    # Source enable snippet (now also respects disable) + helper for extra activation
    [ -x /home/agx/agentforge/bin/enable_rust_flywheel.sh ] && source /home/agx/agentforge/bin/enable_rust_flywheel.sh 2>/dev/null || true
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

case $AGENT in
  grok)
    bash /home/agx/agentforge/agents/grok_runner.sh "$TASK_ID" "$DESC" "/home/agx/planlytasksko" "$PRIORITY" "$SKILL" &
    ;;
  jules)
    bash /home/agx/agentforge/agents/jules_runner.sh "$TASK_ID" "$DESC" &
    ;;
  agy)
    bash /home/agx/agentforge/agents/agy_runner.sh "$TASK_ID" "$DESC" &
    ;;
  gemini)
    bash /home/agx/agentforge/agents/gemini_runner.sh "$TASK_ID" "$DESC" &
    ;;
  antigravity)
    # Вариант A (см. AGENTFORGE_ROUTING_AND_EXECUTION_REFACTOR_PLAN.md)
    # Antigravity сейчас в основном human-in-the-loop режим.
    # Мы не пускаем задачу в автоматический раннер, а явно сигнализируем,
    # что требуется глубокий разбор человеком / через Antigravity IDE чат.
    echo "[AgentForge] ⚠️  Задача $TASK_ID назначена на Antigravity (требует человеческого/архитектурного внимания)"
    echo "[AgentForge]     Открой Antigravity IDE чат и возьми задачу вручную."

    # Помечаем задачу понятным образом, чтобы она не висела в limbo
    curl -s -X PATCH "http://localhost:8080/tasks/$TASK_ID" \
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
