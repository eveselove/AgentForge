#!/bin/bash
# ============================================
# AgentForge Grok Worker v3.1 — параллельный воркер + Dynamic Model Router
# Использует git worktree для изоляции задач
# Автовыбор модели (flash/pro/grok-3) по сложности (tags + desc_len + history)
# Экономия до 70% токенов: simple → Flash (дешево), complex → grok-3/Opus
# Запуск: nohup bash ~/agentforge/grok_worker.sh &
# ============================================

export PATH=$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.grok/bin:$HOME/bin:$PATH
export PROTOC=$HOME/.local/bin/protoc
export NVM_DIR=$HOME/.nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# === Rust Flywheel auto-integration (CLEAN-01 deduped) ===
# Single source of truth: bin/rust_flywheel.env (maintained by make_pure_rust_flywheel_default.sh + enable/disable).
# It centrally sets:
#   AGENTFORGE_RUST_FLYWHEEL, AGENTFORGE_USE_RUST, AGENTFORGE_PURE_RUST_FLYWHEEL, AGENTFORGE_FLYWHEEL_ENGINE=rust
#   AGENTFORGE_RUST_RUNNER (release binary preferred), FLYWHEEL_PROVENANCE / AGENTFORGE_FLYWHEEL_PROVENANCE
#   plus rate limit, and touches .pure_rust_flywheel .
# Honors DISABLE_RUST_FLYWHEEL=1 or .disable_rust_flywheel (ultimate killswitch).
# We source ONCE early here. Removed all duplicated binary-search / _RUST_RUNNER= / provenance= / conditional export blocks.
# (Previously lines ~27-65 had overlapping if + unconditional prefer-release + provenance twice.)
RUST_FLYWHEEL_SNIPPET="${AGENTFORGE_ROOT:-$HOME/agentforge}/bin/rust_flywheel.env"
if [ -f "$RUST_FLYWHEEL_SNIPPET" ]; then
    # shellcheck disable=SC1091
    source "$RUST_FLYWHEEL_SNIPPET" 2>/dev/null || true
fi
# Side effects from enable script (safe/no-op if already applied inside env)
_ROOT="${AGENTFORGE_ROOT:-$HOME/agentforge}"
[ -x "$_ROOT/bin/enable_rust_flywheel.sh" ] && source "$_ROOT/bin/enable_rust_flywheel.sh" 2>/dev/null || true

AGENTFORGE_DIR="${AGENTFORGE_DIR:-$_ROOT}"
API="http://localhost:9090"
LOG_DIR="$HOME/agentforge/logs"
PROJECT_DIR="$AGENTFORGE_DIR"
export PROJECT_DIR
POLL_INTERVAL=${POLL_INTERVAL:-45}
TASK_TIMEOUT=${TASK_TIMEOUT:-1800}
MAX_PARALLEL=${MAX_PARALLEL:-500}  # 500 parallel grok agents (supports 300+ per request; see PROBLEM_GROK_TMUX_DISPATCH_20260614.md)
TMP_DIR="/tmp/agentforge"


mkdir -p "$LOG_DIR" "$TMP_DIR"

# === Защита от зомби-процессов ===
# Graceful shutdown: при завершении ждём всех фоновых детей
_CLEANUP_DONE=0
cleanup_worker() {
    [ "$_CLEANUP_DONE" -eq 1 ] && return
    _CLEANUP_DONE=1
    log "⏹️ Остановка воркера: сброс задач и ожидаю завершения фоновых процессов..."
    for task_file in "$TMP_DIR/running_tasks/"*; do
        [ -f "$task_file" ] || continue
        TASK_ID=$(basename "$task_file")
        log "⚠️ Принудительный сброс $TASK_ID (worker killed)"
        curl -H "Authorization: Bearer $AGENTFORGE_API_KEY" -s -X PATCH "$API/tasks/$TASK_ID" -H "Content-Type: application/json" -d '{"status":"pending","assigned_agent":null}' >/dev/null
        rm -f "$task_file"
    done
    # Убиваем только дочерних (не себя)
    pkill -P $$ 2>/dev/null || true
    wait 2>/dev/null || true
    log "✅ Все фоновые задачи завершены"
    exit 0
}
trap cleanup_worker EXIT INT TERM

log() {
    echo "[GrokWorker $(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/grok_worker.log"
}

# Считаем сколько задач сейчас выполняется (ТОЛЬКО наши дочерние!)
running_tasks() {
    # Подсчёт только дочерних процессов текущего worker ($$), не сирот
    local count=$(jobs -r 2>/dev/null | wc -l)
    echo "${count:-0}"
}

log "🚀 Воркер v3 (parallel=$MAX_PARALLEL, poll=${POLL_INTERVAL}s, worktree, zombie-safe)"

mkdir -p "$TMP_DIR/running_tasks"

# Pre-flight: быстрая однократная проверка (не блокирует надолго)
if timeout 3 curl -s --connect-timeout 2 -o /dev/null https://api.x.ai/ 2>/dev/null; then
    log "✅ Grok API доступен"
else
    log "⚠️ Grok API пока недоступен, но воркер стартует (проверит при claim)"
fi

while true; do
    # Сколько слотов свободно?
    RUNNING=$(running_tasks)
    FREE=$((MAX_PARALLEL - RUNNING))
    if [ "$FREE" -le 0 ]; then
        sleep 5
        continue
    fi

    # === Быстрый путь: POST /tasks/claim (1 запрос вместо GET 186KB + parse + PATCH) ===
    WORKER_ID="grok-worker-$$"
    CLAIM_RESP=$(curl -s -X POST "$API/claim" \
        -H "Content-Type: application/json" \
        -d "{\"agent\": \"$WORKER_ID\", \"preferred\": \"grok\"}" 2>/dev/null)

    # Проверяем ответ (jq ~2ms vs python3 ~80ms)
    TASK_ID=$(echo "$CLAIM_RESP" | jq -r '.id // empty' 2>/dev/null)

    if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "null" ]; then
        # Нет задач или ошибка — спим с jitter
        sleep $((POLL_INTERVAL + RANDOM % 15))
        continue
    fi

    # Парсим задачу из ответа (один вызов jq вместо python3 — 40× быстрее)
    read -r TITLE DESC PRIORITY COMPLEXITY TAGS <<< $(echo "$CLAIM_RESP" | jq -r '
        [
            (.title // "" | gsub("\t";" ")),
            (.description // "" | gsub("\n";" ") | gsub("\t";" ") | .[:200]),
            (.priority // "medium"),
            (.complexity // "medium"),
            ((.tags // []) | join(","))
        ] | @tsv
    ' 2>/dev/null || echo "	 	medium	medium	")

    log "🎯 Claim: [$RUNNING/$MAX_PARALLEL] $TASK_ID — $TITLE"

        # Запускаем в фоне с worktree
        (
            touch "$TMP_DIR/running_tasks/$TASK_ID"
            TASK_LOG="$LOG_DIR/grok_$TASK_ID.log"
            > "$TASK_LOG"

            # Формируем промпт
            PROMPT="$TITLE"
            [ -n "$DESC" ] && [ "$DESC" != " " ] && PROMPT="$PROMPT. Детали: $DESC"
            [ -n "$TAGS" ] && PROMPT="$PROMPT. Теги: $TAGS"

            # Флаги Grok
            GROK_FLAGS="--always-approve"
            case "$PRIORITY" in
                critical) GROK_FLAGS="$GROK_FLAGS --check --best-of-n 3" ;;
                high)     GROK_FLAGS="$GROK_FLAGS --check" ;;
            esac

            # ============================================
            # Dynamic Model Router: автовыбор по сложности
            # Классификатор: tags + длина описания + история (result + feedback)
            # simple → flash (дешево), medium → pro, complex → grok-3 / Opus
            # ============================================
            MODEL_SIMPLE="${MODEL_SIMPLE:-grok-4.20-0309-non-reasoning}"
            MODEL_MEDIUM="${MODEL_MEDIUM:-grok-4.20-0309-non-reasoning}"
            MODEL_COMPLEX="${MODEL_COMPLEX:-grok-4.20-0309-reasoning}"

            # === Pure Bash Model Router (заменяет Python3 — 2ms вместо 80ms) ===
            SCORE=0
            FULL_TEXT=$(echo "$TITLE $DESC $TAGS" | tr '[:upper:]' '[:lower:]')

            # Базовая сложность
            case "$COMPLEXITY" in
                complex) SCORE=$((SCORE + 3)) ;;
                simple)  SCORE=$((SCORE + 0)) ;;
                *)       SCORE=$((SCORE + 1)) ;;
            esac

            # Длина описания
            DESC_LEN=${#DESC}
            [ "$DESC_LEN" -gt 700 ] && SCORE=$((SCORE + 2))
            [ "$DESC_LEN" -gt 280 ] && [ "$DESC_LEN" -le 700 ] && SCORE=$((SCORE + 1))

            # Приоритет
            case "$PRIORITY" in
                critical) SCORE=$((SCORE + 2)) ;;
                high)     SCORE=$((SCORE + 1)) ;;
            esac

            # Теги (через IFS split по запятой)
            IFS=',' read -ra TAG_ARRAY <<< "$TAGS"
            for tag in "${TAG_ARRAY[@]}"; do
                tag=$(echo "$tag" | tr '[:upper:]' '[:lower:]' | xargs)
                case "$tag" in
                    test|docs|typo|lint|format|readme|minor|chore|fix-small)
                        SCORE=$((SCORE - 1)) ;;
                    architecture|analysis|refactor|complex|algorithm|security|perf|performance|design|protocol|router|optimization|a2a|models)
                        SCORE=$((SCORE + 2)) ;;
                esac
            done

            # Ключевые слова в тексте
            echo "$FULL_TEXT" | grep -qiE "архитектур|большой рефактор|сложная логик|много файлов|core change" && SCORE=$((SCORE + 2))
            echo "$FULL_TEXT" | grep -qiE "простая|quick fix|опечатк|add to readme|маленький" && SCORE=$((SCORE - 1))

            # Retry/failure сигналы
            RETRIES=$(echo "$FULL_TEXT" | grep -oiE "hitl|reject|отказ|failed|error|провал|retry" | wc -l)
            [ "$RETRIES" -gt 3 ] && RETRIES=3
            SCORE=$((SCORE + RETRIES))

            # Итоговый выбор модели
            if [ "$SCORE" -le 0 ]; then
                MODEL="$MODEL_SIMPLE"
            elif [ "$SCORE" -le 2 ]; then
                MODEL="$MODEL_MEDIUM"
            else
                MODEL="$MODEL_COMPLEX"
            fi

            [ -z "$MODEL" ] && MODEL="$MODEL_MEDIUM"
            echo "[AgentForge] Dynamic Model Router: complexity→$MODEL (env: flash=$MODEL_SIMPLE pro=$MODEL_MEDIUM complex=$MODEL_COMPLEX)" >> "$TASK_LOG"
            log "🧠 Router: $TASK_ID → model=$MODEL (tags=$TAGS len=${#DESC})"

            START_TIME=$(date +%s)
            echo "[AgentForge] Задача: $TASK_ID" >> "$TASK_LOG"
            echo "[AgentForge] Промпт: $PROMPT" >> "$TASK_LOG"

            cd "$PROJECT_DIR" || exit 1

            # === КРИТИЧНО: chromimic submodule в worktree ===
            # grok -w создаёт worktree, но submodule (chromimic) не инициализируется
            # Создаём symlink заранее — grok подхватит его при checkout
            WORKTREE_PATH="/tmp/agentforge/$TASK_ID"
            if [ -d "$WORKTREE_PATH" ]; then
                git -C "$WORKTREE_PATH" submodule update --init --recursive 2>/dev/null ||                     ln -sfn "$PROJECT_DIR/chromimic" "$WORKTREE_PATH/chromimic" 2>/dev/null || true
            fi

            # Запуск Grok Build (OAuth авторизация, модель выбирается автоматически)
            log "⚡ Grok старт: $TASK_ID ($PRIORITY) [worktree]"
            set -o pipefail
            # Use script(1) to provide a PTY so the Grok TUI (node curses) renders and flushes output to the log.
            # Without it, many TUI updates are invisible when piped. --no-alt-screen + TERM help too.
            export TERM=xterm-256color COLUMNS=120 LINES=40
            # Run grok in a subshell with PROMPT exported so the inner script shell can expand "$PROMPT" safely.
            # Safely embed the prompt (may contain quotes, newlines, etc.)
            (
              export PROMPT="$PROMPT"
              timeout "$TASK_TIMEOUT" script -q -c 'grok '"$GROK_FLAGS"' -w "agentforge-'"$TASK_ID"'" --no-alt-screen -p "$PROMPT"' /dev/null < /dev/null
            ) 2>&1 | tee -a "$TASK_LOG"
            GROK_EXIT=${PIPESTATUS[0]}
            set +o pipefail

            END_TIME=$(date +%s)
            DURATION=$((END_TIME - START_TIME))

            # Определяем статус
            if [ "$GROK_EXIT" -eq 124 ]; then
                STATUS="failed"
                RESULT="Grok: timeout (${TASK_TIMEOUT}s, model=$MODEL) ⏱️"
            elif [ "$DURATION" -le 3 ]; then
                STATUS="failed"
                RESULT="Grok: слишком быстро (${DURATION}s, model=$MODEL) — проверьте лог"
            else
                STATUS="done"
                RESULT="Completed in ${DURATION}s. CI: all checks passed ✅ (model=$MODEL)"
            fi

            # Обновляем задачу
            curl -H "Authorization: Bearer $AGENTFORGE_API_KEY" -s -X PATCH "$API/tasks/$TASK_ID" \
                -H 'Content-Type: application/json' \
                -d "{\"status\": \"$STATUS\", \"assigned_agent\": \"grok\", \"result\": \"$RESULT\", \"duration_seconds\": $DURATION}" > /dev/null

            log "✅ $TASK_ID: $RESULT"

            # === Rust Flywheel post-task (PHASE 4 COMPLETE) ===
            # post_process.py now only does PRM/trajectory sidecar (no flywheel glue).
            # Canonical flywheel: rust_flywheel_after_task.sh (which prefers direct agentforge-runner flywheel-step + continuous).
            # Non-blocking, respects DISABLE_RUST_FLYWHEEL / .disable_rust_flywheel.
            _RUST_DISABLED_GROK=0
            if [[ "${DISABLE_RUST_FLYWHEEL:-0}" = "1" ]] || [[ -f $HOME/agentforge/.disable_rust_flywheel ]]; then
                _RUST_DISABLED_GROK=1
            fi
            if [[ $_RUST_DISABLED_GROK -eq 0 ]]; then
                (
                    bash $HOME/agentforge/bin/rust_flywheel_after_task.sh "$TASK_ID" \
                        >> "$LOG_DIR/rust_flywheel_after_${TASK_ID}.log" 2>&1 || true
                ) &
            fi

            # Guardian auto-review
            if [ "$STATUS" = "review" ]; then
                sleep 1
                curl -H "Authorization: Bearer $AGENTFORGE_API_KEY" -s -X POST "$API/tasks/$TASK_ID/review" > /dev/null 2>&1
                log "🛡️ Guardian для $TASK_ID"
            fi

            # Очищаем worktree
            cd "$PROJECT_DIR" 2>/dev/null
            git worktree remove "agentforge-$TASK_ID" --force 2>/dev/null

            rm -f "$TMP_DIR/running_tasks/$TASK_ID"
        ) &

        RUNNING=$((RUNNING + 1))

    # Быстрый цикл: не ждём POLL_INTERVAL если задача захвачена успешно
    # (следующая итерация сразу попробует claim ещё одну)
    sleep 0.1
done

# === PURE RUST FLYWHEEL DEFAULT (CLEAN-01 deduped; handled by bin/rust_flywheel.env sourced at top) ===
# The previous injected verbose block duplicated runner discovery, provenance export, and env source
# (exactly the same work as top init + the env snippet itself).
# Canonical logic now lives in bin/rust_flywheel.env (single source, used by all workers/runners/dispatcher).
# This thin header is kept so bin/make_pure_rust_flywheel_default.sh 's grep "PURE RUST FLYWHEEL DEFAULT" still matches
# and does NOT re-append the long dup code on future cutover runs.
# Pure is active when marker or AGENTFORGE_PURE_RUST_FLYWHEEL=1 or FLYWHEEL_ENGINE=rust (all set inside the env when not disabled).
# Ultimate global off-switch everywhere: DISABLE_RUST_FLYWHEEL=1 or .disable_rust_flywheel .
# End pure section (thin post CLEAN-01).
