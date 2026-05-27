#!/bin/bash
# AgentForge Dispatcher — запускает задачи через подходящего агента
export PATH=/home/agx/.cargo/bin:/home/agx/.grok/bin:/home/agx/bin:$PATH

TASK_ID="$1"
AGENT="$2"
DESC="$3"
PRIORITY="${4:-medium}"

case $AGENT in
  grok)
    bash /home/agx/agentforge/agents/grok_runner.sh "$TASK_ID" "$DESC" "/home/agx/planlytasksko" "$PRIORITY" &
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
    echo "[AgentForge] Задача $TASK_ID направлена в Antigravity IDE — откройте чат"
    ;;
  *)
    echo "[AgentForge] Неизвестный агент: $AGENT"
    exit 1
    ;;
esac

echo "[AgentForge] Задача $TASK_ID отправлена агенту $AGENT (priority=$PRIORITY)"
