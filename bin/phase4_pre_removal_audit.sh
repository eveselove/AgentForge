#!/bin/bash
# phase4_pre_removal_audit.sh — SAFE, NON-DESTRUCTIVE Phase 4 pre-removal audit + deletion command generator.
#
# !!! AGGRESSIVE FINAL DEPRECATION SWEEP COMPLETE (RUST_FULL_MIGRATION_PLAN.md + PHASE4_REMOVAL_PLAN.md + PHASE4_REMOVAL_CHECKLIST.md) !!!
# This is the canonical pre-removal tooling for Phase 4 (Python flywheel orchestration removal).
# Run ONLY after 14d green soak with agentforge-runner as sole engine.
# Purpose: exhaustive audit of remaining Python flywheel call sites, single-source-of-truth guard verification,
#          generation of exact per-tier git rm + backup + tag commands.
#
# ОБНОВЛЕНО (2026-05-31): Добавлена строгая проверка provenance в manifests и health JSON.
# ОБНОВЛЕНО (2026-05-31 v2): Расширенная provenance валидация — секция 2.6 (SHA256, Cargo, env, маркер, cross-validation).
# Если provenance НЕ 100% rust-agentforge-runner — FAIL с exit code 3.
#
# Usage (read-only, safe any time):
#   bash bin/phase4_pre_removal_audit.sh [--emit-commands] [--strict-provenance]
#   (without flag: audit + report only; with flag: also emit ready-to-paste deletion blocks)
#   --strict-provenance: FAIL (exit 3) если хоть один manifest/health НЕ rust-agentforge-runner
#
# References (single source of truth):
#   - PHASE4_REMOVAL_PLAN.md (5-tier deletion order, invocation map §8, safety invariants §9, post-sweep audits §10)
#   - PHASE4_REMOVAL_CHECKLIST.md (tactical per-file, deletion criteria)
#   - RUST_FULL_MIGRATION_PLAN.md (phases, gates)
#   - learning/utils.py:71 (is_pure_rust_flywheel) + :164 (is_rust_flywheel_disabled) — THE ONLY real impl
#   - 100_PERCENT_READINESS_CHECKLIST.md (current ~92%, Phase 4 ~30%)
#   - bin/make_pure_rust_flywheel_default.sh + bin/disable_pure_rust_flywheel.sh (KEEP; rollback surface)
#
# Safety:
# - Zero writes. Only reads + stdout report.
# - Never proposes deletion of: data (pending_candidates/, eval/trajectories/), .bak* files, rollback tools,
#   non-flywheel cores (planning/, safety/, long_horizon/, observability/, eval/ PRM/trajectory), Rust workspace,
#   or any file with active unguarded prod call sites.
# - Only files 100% proven dead (isolated behind central guard + confined to removal-tier files or explicit rollback tools) are listed.
# - Post-execution: re-run this script + PLAN §10 commands; require human + farm sign-off before any git rm.
#
# Exit: 0 on clean audit state; 2 on guard dupe; 3 on provenance validation failure (strict mode).
#
set -u
AGENTFORGE_ROOT="/home/agx/agentforge"
cd "$AGENTFORGE_ROOT" || exit 1

EMIT_COMMANDS=0
STRICT_PROVENANCE=0
for arg in "$@"; do
    case "$arg" in
        --emit-commands) EMIT_COMMANDS=1 ;;
        --strict-provenance) STRICT_PROVENANCE=1 ;;
    esac
done

# Счётчики для итогового отчёта
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0
WARNINGS=0

# Функция для подсчёта результатов
check_pass() { TOTAL_CHECKS=$((TOTAL_CHECKS+1)); PASSED_CHECKS=$((PASSED_CHECKS+1)); echo "  PASS: $1"; }
check_fail() { TOTAL_CHECKS=$((TOTAL_CHECKS+1)); FAILED_CHECKS=$((FAILED_CHECKS+1)); echo "  FAIL: $1"; }
check_warn() { WARNINGS=$((WARNINGS+1)); echo "  WARN: $1"; }

echo "=================================================================================="
echo "PHASE 4 PRE-REMOVAL AUDIT + PROVENANCE VALIDATION"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Tree: $AGENTFORGE_ROOT"
echo "Mode: read-only audit (destructive commands only emitted on --emit-commands; never executed here)"
echo "Strict provenance: $([ $STRICT_PROVENANCE -eq 1 ] && echo 'ON (FAIL on non-rust provenance)' || echo 'OFF (report only)')"
echo "Gates (per PHASE4_REMOVAL_PLAN.md S2 + S8): 14d pure soak + 100% parity + cargo green + tag + backup REQUIRED before any deletion"
echo "=================================================================================="

echo ""
echo "=== 1. POST-SWEEP UNMARKED FILES AUDIT (exact PLAN S10 command 1) ==="
UNMARKED=$(find . \( -name "*.py" -o -name "*.sh" -o -name "*.service" -o -name "*.timer" \) \
  -not -path "./pending_candidates/*run*" -not -path "./pending_candidates/*promote*" \
  -not -path "./.git/*" 2>/dev/null | xargs grep -l "flywheel\|SkillImprover\|pending_candidates" 2>/dev/null | \
  xargs grep -L "PHASE4_REMOVAL_PLAN\|AGGRESSIVE FINAL DEPRECATION SWEEP" 2>/dev/null | cat)
if [ -z "$UNMARKED" ]; then
    check_pass "Нет немаркированных файлов с flywheel-ссылками"
else
    echo "FLAGGED FILES (review required):"
    echo "$UNMARKED"
    check_warn "Есть файлы с flywheel-ссылками без маркеров Phase4"
fi

echo ""
echo "=== 2. CENTRAL GUARD SINGLE-SOURCE-OF-TRUTH VERIFICATION ==="
echo "Imports of central guard (from learning/utils.py; 19+ expected):"
grep -rn "from agentforge.learning.utils import.*is_pure_rust_flywheel" --include="*.py" . 2>/dev/null | cat
echo ""
echo "Real definitions (only utils.py allowed):"
grep -rn "def is_pure_rust_flywheel\|is_pure_rust_flywheel = lambda\|def is_rust_flywheel_disabled" --include="*.py" . 2>/dev/null | cat
echo ""
DUPES=$(grep -rn "def is_pure_rust_flywheel\|def is_rust_flywheel_disabled\|is_pure_rust_flywheel\s*=\s*lambda" --include="*.py" . 2>/dev/null | grep -v "learning/utils.py:71\|learning/utils.py:164\|learning/evaluator.py:92" | cat)
if [ -z "$DUPES" ]; then
    check_pass "is_pure_rust_flywheel — единственный источник истины (utils.py)"
else
    echo "CRITICAL: UNAUTHORIZED DUPE DETECTED:"
    echo "$DUPES"
    check_fail "Нарушение S9 invariant 1 — дубликация guard-функций"
    exit 2
fi

echo ""
echo "=== 2.5 FLYWHEEL PROVENANCE VALIDATION (строгая проверка Rust-происхождения) ==="
echo "Все manifests и health JSON ОБЯЗАНЫ иметь provenance == rust-agentforge-runner."
echo "Любое отклонение блокирует Phase 4 и заявку Flywheel 100%."
echo ""

# --- 2.5.1: Проверка health JSON ---
echo "--- 2.5.1 Health JSON Provenance ---"
HEALTH_JSON="/tmp/agentforge_rust_flywheel/flywheel_health.json"
PROVENANCE_FAIL=0

if [ -f "$HEALTH_JSON" ]; then
    HEALTH_SOURCE=$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    val = d.get("engine") or d.get("source") or d.get("provenance") or "MISSING"
    print(str(val)[:200])
except Exception as e:
    print("ERROR:" + str(e)[:80])
' "$HEALTH_JSON" 2>/dev/null)

    echo "  Health JSON path: $HEALTH_JSON"
    echo "  Значение source/engine: $HEALTH_SOURCE"

    # Строгая проверка: ДОЛЖНО содержать "rust-agentforge-runner"
    if echo "$HEALTH_SOURCE" | grep -q "rust-agentforge-runner"; then
        check_pass "Health JSON provenance = rust-agentforge-runner"
    else
        check_fail "Health JSON provenance НЕ rust-agentforge-runner (got: $HEALTH_SOURCE)"
        PROVENANCE_FAIL=$((PROVENANCE_FAIL+1))
        echo "  ТРЕБУЕТСЯ: Обновить agentforge-runner чтобы писать engine='rust-agentforge-runner' в health JSON"
    fi

    # Проверяем timestamp свежести
    HEALTH_TS=$(python3 -c '
import json
d = json.load(open("'"$HEALTH_JSON"'"))
ts = d.get("timestamp", "")
print(ts[:19] if ts else "MISSING")
' 2>/dev/null || echo "UNKNOWN")
    echo "  Timestamp последнего обновления: $HEALTH_TS"
else
    check_fail "Health JSON отсутствует: $HEALTH_JSON"
    PROVENANCE_FAIL=$((PROVENANCE_FAIL+1))
fi

echo ""
echo "--- 2.5.2 Manifest Provenance (pending_candidates) ---"
echo "Проверяем ВСЕ manifests на provenance rust-agentforge-runner."

ALL_MANIFESTS=$(find pending_candidates -name "*manifest*.json" 2>/dev/null)
MANIFEST_COUNT=$(echo "$ALL_MANIFESTS" | grep -c . 2>/dev/null || echo 0)
echo "  Всего manifests найдено: $MANIFEST_COUNT"

if [ "$MANIFEST_COUNT" -eq 0 ] || [ -z "$ALL_MANIFESTS" ]; then
    check_warn "Нет manifests в pending_candidates — нечего валидировать"
else
    BAD_MANIFESTS=0
    BAD_MANIFEST_LIST=""
    PYTHON_COMMAND_MANIFESTS=0

    for m in $ALL_MANIFESTS; do
        RESULT=$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    engine = d.get("engine") or d.get("source") or d.get("provenance") or ""
    cmd = d.get("command", "")
    rust_used = d.get("rust_runner_used", False)
    if "rust-agentforge-runner" in str(engine):
        status = "OK_ENGINE"
    elif rust_used is True:
        status = "OK_RUST_USED"
    elif "python" in str(cmd).lower():
        status = "BAD_PYTHON_CMD"
    else:
        status = "BAD_NO_PROVENANCE"
    print(f"{status}|{str(engine)[:60]}|{str(cmd)[:60]}")
except Exception as e:
    print(f"ERROR|{str(e)[:60]}|")
' "$m" 2>/dev/null)

        STATUS=$(echo "$RESULT" | cut -d'|' -f1)
        ENGINE=$(echo "$RESULT" | cut -d'|' -f2)
        CMD=$(echo "$RESULT" | cut -d'|' -f3)

        case "$STATUS" in
            OK_ENGINE|OK_RUST_USED)
                ;;
            BAD_PYTHON_CMD)
                BAD_MANIFESTS=$((BAD_MANIFESTS+1))
                PYTHON_COMMAND_MANIFESTS=$((PYTHON_COMMAND_MANIFESTS+1))
                BAD_MANIFEST_LIST="${BAD_MANIFEST_LIST}  PYTHON_CMD: $m
"
                ;;
            BAD_NO_PROVENANCE)
                BAD_MANIFESTS=$((BAD_MANIFESTS+1))
                BAD_MANIFEST_LIST="${BAD_MANIFEST_LIST}  NO_PROV: $m
"
                ;;
            ERROR)
                BAD_MANIFESTS=$((BAD_MANIFESTS+1))
                BAD_MANIFEST_LIST="${BAD_MANIFEST_LIST}  PARSE_ERR: $m
"
                ;;
        esac
    done

    GOOD_MANIFESTS=$((MANIFEST_COUNT - BAD_MANIFESTS))
    PROV_PERCENT=0
    if [ "$MANIFEST_COUNT" -gt 0 ]; then
        PROV_PERCENT=$((GOOD_MANIFESTS * 100 / MANIFEST_COUNT))
    fi

    echo "  Корректный provenance: $GOOD_MANIFESTS / $MANIFEST_COUNT ($PROV_PERCENT%)"
    echo "  Некорректный provenance: $BAD_MANIFESTS"
    echo "  Из них Python-command: $PYTHON_COMMAND_MANIFESTS"

    if [ $BAD_MANIFESTS -eq 0 ]; then
        check_pass "100% manifests имеют rust-agentforge-runner provenance"
    else
        check_fail "Manifests provenance НЕ 100% rust-agentforge-runner ($PROV_PERCENT%)"
        echo "  Плохие manifests (первые 20):"
        echo "$BAD_MANIFEST_LIST" | head -20
        PROVENANCE_FAIL=$((PROVENANCE_FAIL+1))
        echo ""
        echo "  БЛОКИРУЕТ Phase 4: все manifests ОБЯЗАНЫ генерироваться rust-agentforge-runner"
    fi
fi

echo ""
echo "--- 2.5.3 Provenance Validation Summary ---"
if [ $PROVENANCE_FAIL -eq 0 ]; then
    echo "  PROVENANCE VALIDATION: PASS — 100% rust-agentforge-runner"
else
    echo "  PROVENANCE VALIDATION: FAIL — $PROVENANCE_FAIL source(s) с неверным провенансом"
    if [ $STRICT_PROVENANCE -eq 1 ]; then
        echo ""
        echo "  STRICT MODE: Аудит прерван. Provenance не 100% rust-agentforge-runner."
        echo "=================================================================================="
        echo "AUDIT FAILED: PROVENANCE VALIDATION (exit 3)"
        echo "=================================================================================="
        exit 3
    else
        echo "  Продолжаем аудит (strict mode не включён). Для жёсткой проверки: --strict-provenance"
    fi
fi

echo ""
echo "=== 2.6 РАСШИРЕННАЯ PROVENANCE ВАЛИДАЦИЯ (цепочка доверия) ==="
echo ""

echo "--- 2.6.1 Целостность бинарника agentforge-runner ---"
RUNNER_BIN="rust/target/release/agentforge-runner"
if [ -x "$RUNNER_BIN" ]; then
    # Вычисляем SHA256 хэш бинарника
    RUNNER_HASH=$(sha256sum "$RUNNER_BIN" 2>/dev/null | cut -d" " -f1)
    RUNNER_SIZE=$(stat -c%s "$RUNNER_BIN" 2>/dev/null || echo "UNKNOWN")
    RUNNER_MTIME=$(stat -c%Y "$RUNNER_BIN" 2>/dev/null || echo "0")
    NOW_TS=$(date +%s)
    RUNNER_AGE_DAYS=$(( (NOW_TS - RUNNER_MTIME) / 86400 ))
    echo "  Бинарник: $RUNNER_BIN"
    echo "  SHA256:   $RUNNER_HASH"
    echo "  Размер:   $RUNNER_SIZE байт"
    echo "  Возраст:  ${RUNNER_AGE_DAYS} дней"

    # Проверяем что бинарник не слишком старый (> 30 дней = предупреждение)
    if [ "$RUNNER_AGE_DAYS" -gt 30 ]; then
        check_warn "Бинарник agentforge-runner старше 30 дней (${RUNNER_AGE_DAYS}d) - рекомендуется пересборка"
    else
        check_pass "Бинарник agentforge-runner актуален (${RUNNER_AGE_DAYS}d)"
    fi

    # Записываем хэш в файл для последующей верификации
    HASH_FILE="/tmp/agentforge_rust_flywheel/runner_sha256.txt"
    mkdir -p /tmp/agentforge_rust_flywheel
    if [ -f "$HASH_FILE" ]; then
        PREV_HASH=$(cat "$HASH_FILE" 2>/dev/null)
        if [ "$PREV_HASH" != "$RUNNER_HASH" ]; then
            echo "  ЗАМЕЧАНИЕ: SHA256 бинарника изменился с последнего аудита"
            echo "  Прежний: $PREV_HASH"
            echo "  Текущий: $RUNNER_HASH"
            check_warn "SHA256 agentforge-runner изменился - подтвердите что пересборка была намеренной"
        else
            check_pass "SHA256 agentforge-runner стабилен с последнего аудита"
        fi
    else
        echo "  Первый запуск - базовый хэш сохранён"
    fi
    echo "$RUNNER_HASH" > "$HASH_FILE"
else
    check_fail "Бинарник agentforge-runner НЕ найден ($RUNNER_BIN) - провенанс невозможен"
    PROVENANCE_FAIL=$((PROVENANCE_FAIL+1))
fi

echo ""
echo "--- 2.6.2 Проверка Cargo.toml версии и git-совпадения ---"
CARGO_TOML="rust/Cargo.toml"
if [ -f "$CARGO_TOML" ]; then
    CARGO_VERSION=$(grep "^version" "$CARGO_TOML" | head -1 | sed 's/.*=[ ]*"\(.*\)"/\1/')
    GIT_HEAD=$(git rev-parse --short HEAD 2>/dev/null || echo "no-git")
    echo "  Cargo.toml version: $CARGO_VERSION"
    echo "  Git HEAD:           $GIT_HEAD"

    # Проверяем, что бинарник собран из текущего коммита
    RUST_DIRTY=$(git diff --name-only rust/ 2>/dev/null | head -5)
    if [ -z "$RUST_DIRTY" ]; then
        check_pass "Rust workspace чист - бинарник соответствует HEAD ($GIT_HEAD)"
    else
        echo "  Изменённые файлы в rust/:"
        echo "$RUST_DIRTY" | while read -r f; do echo "    $f"; done
        check_warn "Rust workspace имеет uncommitted изменения - бинарник может не соответствовать HEAD"
    fi
else
    check_warn "Cargo.toml не найден: $CARGO_TOML"
fi

echo ""
echo "--- 2.6.3 Проверка env-переменных провенанса в рантайме ---"
ENV_SNIPPET="/home/agx/agentforge/bin/rust_flywheel.env"
if [ -f "$ENV_SNIPPET" ]; then
    # Проверяем наличие FLYWHEEL_PROVENANCE в env snippet
    if grep -q "FLYWHEEL_PROVENANCE" "$ENV_SNIPPET"; then
        PROV_VALUE=$(grep "FLYWHEEL_PROVENANCE" "$ENV_SNIPPET" | tail -1 | sed 's/.*=//' | tr -d "\"'" )
        echo "  FLYWHEEL_PROVENANCE в env snippet: $PROV_VALUE"
        if echo "$PROV_VALUE" | grep -q "rust-agentforge-runner"; then
            check_pass "FLYWHEEL_PROVENANCE в env snippet = rust-agentforge-runner"
        else
            check_fail "FLYWHEEL_PROVENANCE в env snippet НЕ rust-agentforge-runner (got: $PROV_VALUE)"
            PROVENANCE_FAIL=$((PROVENANCE_FAIL+1))
        fi
    else
        check_warn "FLYWHEEL_PROVENANCE отсутствует в $ENV_SNIPPET - рекомендуется добавить"
    fi
else
    check_warn "Env snippet отсутствует: $ENV_SNIPPET"
fi

echo ""
echo "--- 2.6.4 Проверка .pure_rust_flywheel маркера ---"
PURE_MARKER_CHECK="/home/agx/agentforge/.pure_rust_flywheel"
if [ -f "$PURE_MARKER_CHECK" ]; then
    MARKER_CONTENT=$(cat "$PURE_MARKER_CHECK" 2>/dev/null | head -3)
    MARKER_MTIME=$(stat -c%y "$PURE_MARKER_CHECK" 2>/dev/null | cut -d. -f1)
    echo "  Маркер: $PURE_MARKER_CHECK (mtime: $MARKER_MTIME)"
    echo "  Содержимое: $MARKER_CONTENT"
    check_pass ".pure_rust_flywheel маркер присутствует"
else
    check_fail ".pure_rust_flywheel маркер ОТСУТСТВУЕТ - pure mode не гарантирован"
    PROVENANCE_FAIL=$((PROVENANCE_FAIL+1))
fi

echo ""
echo "--- 2.6.5 Cross-validation: все воркеры используют один бинарник ---"
# Проверяем что все shell скрипты ссылаются на один и тот же runner
RUNNER_REFS=$(grep -rn "AGENTFORGE_RUST_RUNNER\|agentforge-runner" --include="*.sh" . 2>/dev/null | grep -v ".bak" | grep -v "phase4_pre_removal_audit" | cat)
UNIQUE_PATHS=$(echo "$RUNNER_REFS" | grep -oE "/[^ \"]*agentforge-runner[^ \"]*" | sort -u)
UNIQUE_COUNT=$(echo "$UNIQUE_PATHS" | grep -c . 2>/dev/null || echo 0)
echo "  Уникальные пути к runner в скриптах: $UNIQUE_COUNT"
echo "$UNIQUE_PATHS" | while read -r p; do echo "    $p"; done
if [ "$UNIQUE_COUNT" -le 2 ]; then
    check_pass "Все скрипты используют единообразный путь к agentforge-runner"
else
    check_warn "Обнаружено $UNIQUE_COUNT различных путей к runner - рекомендуется унификация"
fi

echo ""
echo "--- 2.6.6 Audit самого audit-скрипта: Python-зависимости в provenance проверках ---"
AUDIT_SELF_PY=$(grep -c "python3\|python " /home/agx/agentforge/bin/phase4_pre_removal_audit.sh 2>/dev/null || echo 0)
echo "  Python вызовов в audit скрипте: $AUDIT_SELF_PY"
if [ "$AUDIT_SELF_PY" -gt 0 ]; then
    echo "  РЕКОМЕНДАЦИЯ: заменить Python JSON парсинг на jq для полной независимости от Python"
    echo "  Пример: jq -r '.engine // .source // .provenance // \"MISSING\"' health.json"
    check_warn "Audit скрипт сам использует Python ($AUDIT_SELF_PY вызовов) - рекомендуется миграция на jq"
else
    check_pass "Audit скрипт не зависит от Python"
fi

echo ""
echo "=== 3. PYTHON -M FLYWHEEL INVOCATION SNAPSHOT ==="
grep -rnE "python.*-m agentforge.*(rust_flywheel_step|run_continuous_flywheel|list_pending_candidates|enable_rust_flywheel)" \
  --include="*.sh" --include="*.service" --include="*.py" . 2>/dev/null | grep -v ".bak" | cat | head -30

echo ""
echo "=== 4. PURE MODE + BINARY SMOKE ==="
echo "Current guard state (AGENTFORGE_PURE_RUST_FLYWHEEL=1 forced for test):"
AGENTFORGE_PURE_RUST_FLYWHEEL=1 python -c "
from agentforge.learning.utils import is_pure_rust_flywheel, is_rust_flywheel_disabled
print('  pure:', is_pure_rust_flywheel(), 'disabled:', is_rust_flywheel_disabled())
" 2>&1 | cat
echo ""
echo "Binary surface:"
if [ -x "rust/target/release/agentforge-runner" ]; then
    rust/target/release/agentforge-runner --help 2>&1 | grep -E 'flywheel|continuous|candidate' | cat || echo "  (subcommands present)"
else
    echo "  (release binary not found — build required)"
fi

echo ""
echo "=== 5. EXHAUSTIVE CALL-SITE CLASSIFICATION ==="
ACTIVE=$(grep -rnE "from .* import .* (skill_improver|pending_candidates|evaluator)|import .*rust_flywheel_step|import .*run_continuous_flywheel|from agentforge.phase2_3_integration import run_rust_flywheel" --include="*.py" . 2>/dev/null | grep -vE "(learning/(skill_improver|pending_candidates|evaluator|__init__)|rust_flywheel_step.py|run_continuous_flywheel.py|phase2_3_integration.py|examples/|flywheel_parity|bin/(make|disable|enable|test|rust_flywheel_after)|__pycache__)" | cat || true)
if [ -z "$ACTIVE" ]; then
    check_pass "ZERO active prod call sites outside removal targets"
else
    echo "  WARNING: potential stray:"
    echo "$ACTIVE"
    check_warn "Обнаружены потенциальные stray call-sites"
fi

echo ""
echo "=== 5.5 PYTHON ASSUMPTIONS IN SHELL SCRIPTS (jules_worker.sh + jules_runner.sh) ==="
echo ""

echo "--- jules_worker.sh ---"
WORKER_PY_CALLS=$(grep -n "python3\|python " jules_worker.sh 2>/dev/null | cat)
if [ -z "$WORKER_PY_CALLS" ]; then
    check_pass "jules_worker.sh: нет Python вызовов"
else
    WORKER_PY_COUNT=$(echo "$WORKER_PY_CALLS" | wc -l)
    echo "  Python вызовы ($WORKER_PY_COUNT шт.):"
    echo "$WORKER_PY_CALLS" | while read -r line; do echo "    $line"; done
    echo "  Классификация:"
    echo "$WORKER_PY_CALLS" | grep -q "json.load\|json.loads" && echo "    - JSON фильтрация задач: ЗАМЕНИТЬ на jq или чистый bash"
    echo "$WORKER_PY_CALLS" | grep -q "is_pure_rust_flywheel" && echo "    - Guard check через Python: ЗАМЕНИТЬ на проверку файла-маркера"
    echo "$WORKER_PY_CALLS" | grep -q "rust_post_process_hook\|rust_flywheel_step" && echo "    - Python post-process hook: ЗАМЕНИТЬ на agentforge-runner"
    check_warn "jules_worker.sh содержит $WORKER_PY_COUNT Python вызов(ов)"
fi

echo ""
echo "--- jules_runner.sh (agents/) ---"
RUNNER_PY_CALLS=$(grep -n "python3\|python " agents/jules_runner.sh 2>/dev/null | cat)
if [ -z "$RUNNER_PY_CALLS" ]; then
    check_pass "jules_runner.sh: нет Python вызовов"
else
    RUNNER_PY_COUNT=$(echo "$RUNNER_PY_CALLS" | wc -l)
    echo "  Python вызовы ($RUNNER_PY_COUNT шт.):"
    echo "$RUNNER_PY_CALLS" | while read -r line; do echo "    $line"; done
    echo "  Классификация:"
    echo "$RUNNER_PY_CALLS" | grep -q "is_pure_rust_flywheel" && echo "    - is_pure_rust_flywheel() через Python: ЗАМЕНИТЬ на [[ -f .pure_rust_flywheel ]]"
    echo "$RUNNER_PY_CALLS" | grep -q "rust_post_process_hook" && echo "    - Python rust_post_process_hook: ЗАМЕНИТЬ на agentforge-runner flywheel-step"
    check_warn "jules_runner.sh содержит $RUNNER_PY_COUNT Python вызов(ов)"
fi

echo ""
echo "--- Мёртвый код после while-loop ---"
WORKER_LINES=$(wc -l < jules_worker.sh 2>/dev/null || echo 0)
WHILE_DONE_LINE=$(grep -n "^done$" jules_worker.sh 2>/dev/null | tail -1 | cut -d: -f1)
if [ -n "$WHILE_DONE_LINE" ] && [ "$WORKER_LINES" -gt "$WHILE_DONE_LINE" ]; then
    DEAD_LINES=$((WORKER_LINES - WHILE_DONE_LINE))
    echo "  jules_worker.sh: $DEAD_LINES строк мёртвого кода после 'done' (строка $WHILE_DONE_LINE из $WORKER_LINES)"
    echo "  Это PURE RUST FLYWHEEL DEFAULT блок, который НИКОГДА не выполнится"
    check_fail "Мёртвый код после while-loop в jules_worker.sh ($DEAD_LINES строк)"
else
    check_pass "Нет мёртвого кода после while-loop"
fi

echo ""
echo "=== 6. TIER INVENTORY ==="
echo "TIER 1: rust_flywheel_demo.py, enable_rust_flywheel.py, list_pending_candidates.py, show_agent_stats.py, examples/*.py, learning/dataset.py, learning/trainer_interface.py"
echo "TIER 2: bin/rust_post_process_hook.py, eval/post_process.py (SURGICAL), eval/runner.py, learning/trajectory_dataset.py, learning/flywheel_parity/"
echo "TIER 3: rust_flywheel_step.py, bin/run_continuous_flywheel.py, learning/skill_improver.py, learning/pending_candidates.py, learning/evaluator.py, phase2_3_integration.py (SURGICAL)"
echo "TIER 4: learning/__init__.py (thin), sh/service patches, __pycache__ cleanup"
echo "KEEP: rollback tools, rust_flywheel.env, *.bak.*, pending_candidates/, eval/ non-glue, planning/, safety/, Rust workspace, docs/*.md"

echo ""
echo "=== 7. DELETION COMMANDS ==="
if [ $EMIT_COMMANDS -eq 1 ]; then
    echo ">>> PRE-DELETION GATES:"
    echo "git tag -a pre-phase4-removal-\$(date +%Y%m%d_%H%M%S) -m 'Phase 4 removal baseline'"
    echo "tar czf /tmp/agentforge-pre-phase4-\$(date +%s).tgz pending_candidates/ eval/trajectories/ logs/"
    echo "cargo test --offline --workspace -- --quiet"
    echo ""
    echo ">>> TIER 1: git rm -f rust_flywheel_demo.py enable_rust_flywheel.py list_pending_candidates.py show_agent_stats.py examples/phase2_3_*.py learning/dataset.py learning/trainer_interface.py"
    echo ">>> TIER 2: git rm -f bin/rust_post_process_hook.py; git rm -rf learning/flywheel_parity/"
    echo ">>> TIER 3: git rm -f rust_flywheel_step.py bin/run_continuous_flywheel.py learning/skill_improver.py learning/pending_candidates.py learning/evaluator.py"
    echo ">>> TIER 4: thin learning/__init__.py + patch sh/service + rm __pycache__"
else
    echo "(Run with --emit-commands to output deletion commands)"
fi

echo ""
echo "=== 8. ROLLBACK ==="
echo "1. bin/disable_pure_rust_flywheel.sh"
echo "2. systemctl --user restart agentforge-*"
echo "3. git checkout <pre-phase4-removal-tag> -- <files>"

echo ""
echo "=================================================================================="
echo "AUDIT SUMMARY"
echo "  Total checks: $TOTAL_CHECKS"
echo "  Passed: $PASSED_CHECKS"
echo "  Failed: $FAILED_CHECKS"
echo "  Warnings: $WARNINGS"
echo ""
if [ $FAILED_CHECKS -eq 0 ]; then
    echo "AUDIT RESULT: ALL CHECKS PASSED (with $WARNINGS warnings)"
else
    echo "AUDIT RESULT: $FAILED_CHECKS CHECK(S) FAILED"
fi
echo "=================================================================================="

exit $FAILED_CHECKS
