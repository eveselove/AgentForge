#!/bin/bash
# PHASE4_REMOVAL_PLAN AGGRESSIVE FINAL DEPRECATION SWEEP: flywheel/soak refs are the purpose of this tool (keep); marker for unmarked audit.
# ============================================================
# soak_daily_report.sh — Ежедневный отчёт soak-мониторинга
# Собирает метрики: fidelity, provenance, fallback counts
# за 14-дневный soak period Pure-Rust Flywheel
# ============================================================
# Использование: bash scripts/soak_daily_report.sh [--day N]
# По умолчанию вычисляет день автоматически от soak_start.txt
# Выход: logs/soak_reports/soak_day_N.json + stdout сводка
# ============================================================

set -euo pipefail

# === Конфигурация ===
AGENTFORGE_DIR="/home/eveselove/agentforge"
HEALTH_JSON="/tmp/agentforge_rust_flywheel/flywheel_health.json"
LOGS_DIR="${AGENTFORGE_DIR}/logs"
SOAK_REPORTS_DIR="${LOGS_DIR}/soak_reports"
PENDING_DIR="${AGENTFORGE_DIR}/pending_candidates"
SOAK_DURATION=0  # 14d bypassed per user directive, immediate launch 2026-06-13 task-ff2e2174
SOAK_START_FILE="${AGENTFORGE_DIR}/soak_start.txt"
CONTINUOUS_LOG="${LOGS_DIR}/continuous_flywheel.log"

# Цвета для вывода
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# === Вспомогательные функции ===

# Инициализация soak_start если не существует
init_soak_start() {
    if [ ! -f "${SOAK_START_FILE}" ]; then
        date '+%Y-%m-%d' > "${SOAK_START_FILE}"
        echo -e "${YELLOW}⚠ Файл soak_start.txt не найден, инициализирован сегодняшней датой${NC}"
    fi
}

# Вычисление текущего дня soak
calc_soak_day() {
    local start_date
    start_date=$(cat "${SOAK_START_FILE}")
    local start_epoch
    start_epoch=$(date -d "${start_date}" '+%s')
    local now_epoch
    now_epoch=$(date '+%s')
    local diff_seconds=$((now_epoch - start_epoch))
    local diff_days=$((diff_seconds / 86400 + 1))
    echo "${diff_days}"
}

# Сбор fidelity метрик из flywheel_health.json
collect_fidelity() {
    if [ ! -f "${HEALTH_JSON}" ]; then
        echo '{"fidelity_ready": false, "error": "health JSON not found"}'
        return
    fi
    # Извлекаем ключевые поля fidelity
    python3 << 'PYEOF'
import json, sys
try:
    with open("/tmp/agentforge_rust_flywheel/flywheel_health.json") as f:
        h = json.load(f)
    result = {
        "fidelity_ready": h.get("fidelity_ready", False),
        "phase": h.get("phase", "unknown"),
        "shadow": h.get("shadow", False),
        "dry_run": h.get("dry_run", True),
        "source": h.get("source", "unknown"),
        "suggested_count": h.get("suggested_count", 0),
        "total_pending_scanned": h.get("total_pending_scanned", 0),
        "timestamp": h.get("timestamp", "unknown"),
        "enable_marker_present": h.get("enable_marker_present", False)
    }
    # Считаем средний success_rate и high_value_count из suggested
    suggested = h.get("suggested", [])
    if suggested:
        avg_success = sum(s.get("success_rate", 0) for s in suggested) / len(suggested)
        total_hv = sum(s.get("high_value_count", 0) for s in suggested)
        result["avg_success_rate"] = round(avg_success, 4)
        result["total_high_value_records"] = total_hv
    else:
        result["avg_success_rate"] = 0.0
        result["total_high_value_records"] = 0
    json.dump(result, sys.stdout)
except Exception as e:
    json.dump({"fidelity_ready": False, "error": str(e)}, sys.stdout)
PYEOF
}

# Подсчёт fallback из proposal.json в pending_candidates
count_fallbacks() {
    local fallback_count=0
    local total_proposals=0
    local rust_native_count=0

    if [ -d "${PENDING_DIR}" ]; then
        # Считаем proposals с rust_flywheel_fallback
        fallback_count=$(grep -rl 'rust_flywheel_fallback' "${PENDING_DIR}" --include='proposal.json' 2>/dev/null | wc -l)
        # Общее количество proposal.json
        total_proposals=$(find "${PENDING_DIR}" -name 'proposal.json' -type f 2>/dev/null | wc -l)
        # Rust-native (не fallback) — разница
        rust_native_count=$((total_proposals - fallback_count))
    fi

    # Fallback из логов (python fallback / FALLBACK в grok логах)
    local log_fallbacks=0
    if [ -d "${LOGS_DIR}" ]; then
        log_fallbacks=$(grep -rc 'python.*fallback\|FALLBACK\|fallback_triggered' "${LOGS_DIR}"/*.log 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')
    fi

    echo "{\"proposal_fallbacks\": ${fallback_count}, \"total_proposals\": ${total_proposals}, \"rust_native\": ${rust_native_count}, \"log_fallbacks\": ${log_fallbacks}}"
}

# Проверка провенанса — все ли proposals имеют source поле
check_provenance() {
    local total=0
    local with_source=0
    local without_source=0

    if [ -d "${PENDING_DIR}" ]; then
        total=$(find "${PENDING_DIR}" -name 'proposal.json' -type f 2>/dev/null | wc -l)
        # Proposals с явным source полем
        with_source=$(grep -rl '"source"' "${PENDING_DIR}" --include='proposal.json' 2>/dev/null | wc -l)
        without_source=$((total - with_source))
    fi

    local pct=0
    if [ "${total}" -gt 0 ]; then
        pct=$(python3 -c "print(round(${with_source}/${total}*100, 1))")
    fi

    echo "{\"total\": ${total}, \"with_provenance\": ${with_source}, \"without_provenance\": ${without_source}, \"provenance_pct\": ${pct}}"
}

# Рассчёт fidelity score (0-100)
calc_fidelity_score() {
    local fidelity_json="$1"
    local fallback_json="$2"
    local provenance_json="$3"

    python3 << PYEOF
import json, sys

fidelity = json.loads('''${fidelity_json}''')
fallback = json.loads('''${fallback_json}''')
provenance = json.loads('''${provenance_json}''')

score = 0
max_score = 100
reasons = []

# 1. Fidelity ready (20 баллов)
if fidelity.get('fidelity_ready'):
    score += 20
    reasons.append('fidelity_ready: +20')
else:
    reasons.append('fidelity NOT ready: +0')

# 2. Shadow mode активен (10 баллов)
if fidelity.get('shadow'):
    score += 10
    reasons.append('shadow_mode: +10')

# 3. Enable marker (10 баллов)
if fidelity.get('enable_marker_present'):
    score += 10
    reasons.append('enable_marker: +10')

# 4. Провенанс >= 90% (20 баллов), пропорционально
prov_pct = provenance.get('provenance_pct', 0)
if prov_pct >= 90:
    score += 20
    reasons.append(f'provenance {prov_pct}%: +20')
elif prov_pct >= 70:
    score += 10
    reasons.append(f'provenance {prov_pct}%: +10')
else:
    reasons.append(f'provenance {prov_pct}%: +0')

# 5. Низкий % fallback (20 баллов)
total = fallback.get('total_proposals', 0)
fb = fallback.get('proposal_fallbacks', 0)
if total > 0:
    fb_pct = fb / total * 100
    if fb_pct <= 10:
        score += 20
        reasons.append(f'fallback {fb_pct:.1f}%: +20')
    elif fb_pct <= 30:
        score += 15
        reasons.append(f'fallback {fb_pct:.1f}%: +15')
    elif fb_pct <= 50:
        score += 10
        reasons.append(f'fallback {fb_pct:.1f}%: +10')
    else:
        score += 5
        reasons.append(f'fallback {fb_pct:.1f}%: +5 (high!)')
else:
    score += 5
    reasons.append('no proposals to check fallback')

# 6. Pending candidates > 0 (10 баллов)
pending = fidelity.get('total_pending_scanned', 0)
if pending > 50:
    score += 10
    reasons.append(f'pending_scanned {pending}: +10')
elif pending > 0:
    score += 5
    reasons.append(f'pending_scanned {pending}: +5')
else:
    reasons.append('no pending scanned: +0')

# 7. Log fallbacks минимальны (10 баллов)
log_fb = fallback.get('log_fallbacks', 0)
if log_fb == 0:
    score += 10
    reasons.append('log_fallbacks 0: +10')
elif log_fb <= 5:
    score += 5
    reasons.append(f'log_fallbacks {log_fb}: +5')
else:
    reasons.append(f'log_fallbacks {log_fb}: +0')

print(json.dumps({'score': score, 'max': max_score, 'breakdown': reasons}))
PYEOF
}

# Определение go/no-go решения
decide_go_nogo() {
    local score=$1
    local day=$2

    if [ "${score}" -ge 80 ]; then
        echo "GO"
    elif [ "${score}" -ge 60 ]; then
        echo "CONDITIONAL"
    else
        echo "NO-GO"
    fi
}

# === Основная логика ===

main() {
    local day_override=""

    # Парсинг аргументов
    while [[ $# -gt 0 ]]; do
        case $1 in
            --day)
                day_override="$2"
                shift 2
                ;;
            --help|-h)
                echo "Использование: $0 [--day N]"
                echo "  --day N  : Установить номер дня soak вручную"
                exit 0
                ;;
            *)
                echo "Неизвестный аргумент: $1"
                exit 1
                ;;
        esac
    done

    # Создаём директорию для отчётов
    mkdir -p "${SOAK_REPORTS_DIR}"

    # Инициализация даты начала soak
    init_soak_start

    # Определяем день soak
    local soak_day
    if [ -n "${day_override}" ]; then
        soak_day="${day_override}"
    else
        soak_day=$(calc_soak_day)
    fi

    # Ограничение: если day > SOAK_DURATION, предупреждаем
    local soak_status="active"
    if [ "${soak_day}" -gt "${SOAK_DURATION}" ]; then
        soak_status="completed"
    fi

    echo -e "${BOLD}${CYAN}"
    echo "╔═══════════════════════════════════════════════════════╗"
    echo "║     🔬 SOAK-MONITOR — Ежедневный отчёт              ║"
    echo "║     Pure-Rust Flywheel IMMEDIATE LAUNCH (14d removed) ║"
    echo "╚═══════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo -e "${BOLD}📅 День: ${soak_day}/${SOAK_DURATION} | Статус: ${soak_status} | Дата: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo ""

    # Собираем метрики
    echo -e "${CYAN}[1/4] Сбор fidelity метрик...${NC}"
    local fidelity_json
    fidelity_json=$(collect_fidelity)

    echo -e "${CYAN}[2/4] Подсчёт fallback...${NC}"
    local fallback_json
    fallback_json=$(count_fallbacks)

    echo -e "${CYAN}[3/4] Проверка провенанса...${NC}"
    local provenance_json
    provenance_json=$(check_provenance)

    echo -e "${CYAN}[4/4] Расчёт fidelity score...${NC}"
    local score_json
    score_json=$(calc_fidelity_score "${fidelity_json}" "${fallback_json}" "${provenance_json}")

    local score
    score=$(echo "${score_json}" | python3 -c "import json,sys; print(json.load(sys.stdin)['score'])")
    local decision
    decision=$(decide_go_nogo "${score}" "${soak_day}")

    # Формируем итоговый JSON отчёт
    local report_file="${SOAK_REPORTS_DIR}/soak_day_${soak_day}.json"
    local soak_start_date
    soak_start_date=$(cat "${SOAK_START_FILE}")

    python3 << PYEOF
import json
from datetime import datetime

report = {
    "soak_day": ${soak_day},
    "soak_duration": ${SOAK_DURATION},
    "soak_status": "${soak_status}",
    "date": datetime.now().isoformat(),
    "soak_start": "${soak_start_date}",
    "fidelity": json.loads('''${fidelity_json}'''),
    "fallbacks": json.loads('''${fallback_json}'''),
    "provenance": json.loads('''${provenance_json}'''),
    "score": json.loads('''${score_json}'''),
    "decision": "${decision}"
}

with open("${report_file}", "w") as f:
    json.dump(report, f, indent=2)
PYEOF

    # Красивая сводка
    echo ""
    echo -e "${BOLD}════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}  📊 СВОДКА SOAK — День ${soak_day}/${SOAK_DURATION}${NC}"
    echo -e "${BOLD}════════════════════════════════════════════════${NC}"

    # Fidelity
    local fidelity_ready
    fidelity_ready=$(echo "${fidelity_json}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('fidelity_ready', False))")
    if [ "${fidelity_ready}" = "True" ]; then
        echo -e "  ${GREEN}✅${NC} Fidelity Ready:     ${GREEN}ДА${NC}"
    else
        echo -e "  ${RED}❌${NC} Fidelity Ready:     ${RED}НЕТ${NC}"
    fi

    # Fallback
    local fb_count
    fb_count=$(echo "${fallback_json}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('proposal_fallbacks', 0))")
    local total_proposals
    total_proposals=$(echo "${fallback_json}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total_proposals', 0))")
    echo -e "  ${YELLOW}📉${NC} Fallback Count:     ${fb_count}/${total_proposals} proposals"

    # Провенанс
    local prov_pct
    prov_pct=$(echo "${provenance_json}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('provenance_pct', 0))")
    if python3 -c "import sys; sys.exit(0 if float('${prov_pct}') >= 90 else 1)"; then
        echo -e "  ${GREEN}✅${NC} Provenance:         ${GREEN}${prov_pct}%${NC}"
    else
        echo -e "  ${YELLOW}⚠️${NC}  Provenance:         ${YELLOW}${prov_pct}%${NC}"
    fi

    # Score
    if [ "${score}" -ge 80 ]; then
        echo -e "  ${GREEN}🏆${NC} Fidelity Score:     ${GREEN}${score}/100${NC}"
    elif [ "${score}" -ge 60 ]; then
        echo -e "  ${YELLOW}📊${NC} Fidelity Score:     ${YELLOW}${score}/100${NC}"
    else
        echo -e "  ${RED}📊${NC} Fidelity Score:     ${RED}${score}/100${NC}"
    fi

    # Go/No-Go
    if [ "${decision}" = "GO" ]; then
        echo -e "  ${GREEN}🚀${NC} Решение:            ${GREEN}${BOLD}GO${NC}"
    elif [ "${decision}" = "CONDITIONAL" ]; then
        echo -e "  ${YELLOW}⚡${NC} Решение:            ${YELLOW}${BOLD}CONDITIONAL${NC}"
    else
        echo -e "  ${RED}🛑${NC} Решение:            ${RED}${BOLD}NO-GO${NC}"
    fi

    echo -e "${BOLD}════════════════════════════════════════════════${NC}"
    echo -e "  📁 Отчёт сохранён: ${report_file}"
    echo -e "${BOLD}════════════════════════════════════════════════${NC}"
}

main "$@"
