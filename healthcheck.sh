#!/bin/bash
# ============================================
# AgentForge Health Check — проверка всей системы
# Запуск: bash ~/agentforge/healthcheck.sh
# ============================================

export PATH=/home/agx/.grok/bin:/home/agx/.cargo/bin:/home/agx/bin:$PATH
export NVM_DIR=/home/agx/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

API="http://localhost:8080"
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
    TOTAL=$(echo "$METRICS" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_tasks'])")
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
if [ -f "/home/agx/.grok/bin/grok" ]; then
    VER=$(/home/agx/.grok/bin/grok --version 2>/dev/null | head -1)
    echo -e "  ${GREEN}✅${NC} Grok CLI            $VER"
else
    echo -e "  ${RED}❌${NC} Grok CLI            NOT INSTALLED"
fi

# 5. Jules CLI
JULES_PATH=$(find /home/agx/.nvm -name 'jules' -type f 2>/dev/null | head -1)
if [ -n "$JULES_PATH" ]; then
    echo -e "  ${GREEN}✅${NC} Jules CLI           $JULES_PATH"
else
    echo -e "  ${RED}❌${NC} Jules CLI           NOT INSTALLED"
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
DISK=$(df -h /home/agx | tail -1 | awk '{print $4}')
echo -e "  ${GREEN}✅${NC} Disk Space          $DISK free"

# 10. Uptime
UP=$(uptime -p)
echo -e "  ${GREEN}✅${NC} System              $UP"

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
