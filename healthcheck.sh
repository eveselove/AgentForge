#!/bin/bash
# ============================================
# AgentForge Health Check — проверка всей системы
# Запуск: bash ~/agentforge/healthcheck.sh
# ============================================
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md) !!!
# Healthcheck touches flywheel services (agentforge-flywheel.timer, watchdog) + worker post hooks.
# Flywheel orchestration now driven exclusively by agentforge-runner (continuous / flywheel-step).
# Python paths (watchdog.py flywheel bits, old hooks) deprecated per Phase 4.
# See PHASE4_REMOVAL_PLAN.md (Tier 4 infra/services, Tier 3 hooks) for removal order, risks, rollback.
# Under pure: services invoke binary directly; health from /tmp/.../flywheel_health.json + Rust JSON.
# Rollback: use disable_pure_rust_flywheel.sh or set env + restart services.

export PATH=/home/eveselove/.grok/bin:/home/eveselove/.cargo/bin:/home/eveselove/bin:$PATH
export NVM_DIR=/home/eveselove/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

API="http://localhost:9090"
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================="
echo "  🏗️  AgentForge System Health Check"
echo "============================================="

# 1. Task Queue API
if curl -s "$API/health" | grep -q '"ok"'; then
    echo -e "  ${GREEN}✅${NC} Task Queue API      ONLINE"
else
    echo -e "  ${RED}❌${NC} Task Queue API      OFFLINE"
fi

# 2. Метрики
METRICS=$(curl -s "$API/metrics" 2>/dev/null)
if [ -n "$METRICS" ]; then
    TOTAL=$(echo "$METRICS" | jq -r '.total_tasks // "N/A"' 2>/dev/null || echo "N/A")
    echo -e "  ${GREEN}✅${NC} Metrics API         OK ($TOTAL tasks)"
else
    echo -e "  ${RED}❌${NC} Metrics API         FAIL"
fi

# 3. Dashboard
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API/dashboard" 2>/dev/null)
if [ "$CODE" = "200" ]; then
    echo -e "  ${GREEN}✅${NC} Dashboard           OK"
else
    echo -e "  ${RED}❌${NC} Dashboard           FAIL ($CODE)"
fi

# 4. Grok CLI
if [ -f "/home/eveselove/.grok/bin/grok" ]; then
    VER=$(/home/eveselove/.grok/bin/grok --version 2>/dev/null | head -1)
    echo -e "  ${GREEN}✅${NC} Grok CLI            $VER"
else
    echo -e "  ${RED}❌${NC} Grok CLI            NOT INSTALLED"
fi


# 6. GEMINI.md
if [ -f "$HOME/.gemini/GEMINI.md" ]; then
    SIZE=$(wc -c < "$HOME/.gemini/GEMINI.md")
    echo -e "  ${GREEN}✅${NC} GEMINI.md           OK (${SIZE}B)"
else
    echo -e "  ${YELLOW}⚠️${NC} GEMINI.md           MISSING"
fi

# 7. Автозапуск
if crontab -l 2>/dev/null | grep -q "agentforge\|task_queue"; then
    echo -e "  ${GREEN}✅${NC} Autostart (cron)    CONFIGURED"
else
    echo -e "  ${YELLOW}⚠️${NC} Autostart (cron)    NOT SET"
fi

# 8. Grok Worker
WORKER_PID=$(pgrep -f "grok_worker" 2>/dev/null)
if [ -n "$WORKER_PID" ]; then
    echo -e "  ${GREEN}✅${NC} Grok Worker         RUNNING (PID: $WORKER_PID)"
else
    echo -e "  ${YELLOW}⚠️${NC} Grok Worker         STOPPED"
fi

# 9. Свободное место
DISK=$(df -h /home/eveselove | tail -1 | awk '{print $4}')
echo -e "  ${GREEN}✅${NC} Disk Space          $DISK free"

# 10. Uptime
UP=$(uptime -p)
echo -e "  ${GREEN}✅${NC} System              $UP"

# 11. Continuous Flywheel Autonomy Timer (Production Rolled Out - 24/7 self-improvement)
# Reuses ENABLE_RUST_FLYWHEEL exactly; non-breaking. Checks both user + system modes.
FLY_TIMER_ACTIVE=0
FLY_MODE=""
if systemctl --user is-active --quiet agentforge-flywheel.timer 2>/dev/null; then
    FLY_TIMER_ACTIVE=1
    FLY_MODE="user"
elif systemctl is-active --quiet agentforge-flywheel.timer 2>/dev/null; then
    FLY_TIMER_ACTIVE=1
    FLY_MODE="system"
fi
if [ $FLY_TIMER_ACTIVE -eq 1 ]; then
    echo -e "  ${GREEN}✅${NC} Flywheel Timer      ACTIVE ($FLY_MODE, 20min Persistent+Randomized)"
else
    echo -e "  ${YELLOW}⚠️${NC} Flywheel Timer      INACTIVE (enable via bin/enable_continuous_flywheel.sh)"
fi
# Health snapshot from continuous (written by run + polled deeply by watchdog)
if [ -f "/tmp/agentforge_rust_flywheel/flywheel_health.json" ]; then
    FLY_LAST=$(python3 -c '
import json,sys,time,os
try:
    h=json.load(open("/tmp/agentforge_rust_flywheel/flywheel_health.json"))
    ts=h.get("timestamp","")
    last=h.get("last_continuous",{}).get("finished_at","")
    cands=h.get("candidates_last_hour",0)
    rich = h.get("rich_exports") or {}
    sr = rich.get("success_rate")
    consec = rich.get("consecutive_failures",0)
    degraded = h.get("degraded", False)
    last_s = rich.get("last_success_iso") or "n/a"
    print(f"health: cands_last_h={cands} last_cont={str(last)[:16] if last else \"n/a\"} rich_sr={sr} consec_fails={consec} degraded={degraded} last_rich_succ={str(last_s)[:16]}")
except Exception as e: print("health: parse-err")
' 2>/dev/null || echo "health: n/a")
    echo -e "  ${GREEN}✅${NC} Flywheel Health     $FLY_LAST"
else
    echo -e "  ${YELLOW}⚠️${NC} Flywheel Health     no snapshot (run continuous once)"
fi

echo "============================================="
echo ""

# Краткая сводка задач
echo "📊 Задачи:"
curl -s "$API/metrics" 2>/dev/null | python3 -c "
import sys, json
m = json.load(sys.stdin)
bs = m.get('by_status', {})
ba = m.get('by_agent', {})
print(f'  Pending: {bs.get(\"pending\",0)} | Dispatched: {bs.get(\"dispatched\",0)} | Review: {bs.get(\"review\",0)} | Done: {bs.get(\"done\",0)}')
print(f'  По агентам: {ba}')
ap = m.get('agent_performance', {})
if ap:
    print(f'  Производительность: {ap}')
"
echo ""

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
