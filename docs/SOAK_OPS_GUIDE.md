# 🔬 Soak Operations Guide — 14-дневный мониторинг Pure-Rust Flywheel

> Версия: 1.0 | Дата: 2026-05-31
> Автор: AgentForge / Antigravity

## Обзор

Soak-мониторинг — это 14-дневный период наблюдения за Pure-Rust Flywheel после миграции
с Python. Цель — убедиться, что:
- Fidelity метрики стабильны
- Fallback на Python минимален
- Провенанс данных сохраняется
- Система готова к полному переходу (GO/NO-GO решение)

## Текущий стек мониторинга

```
┌─────────────────────────────────────────────────┐
│              SOAK MONITORING STACK               │
├─────────────────────────────────────────────────┤
│                                                  │
│  soak_daily_report.sh → soak_day_N.json          │
│       │                                          │
│       ├── collect_fidelity()                     │
│       │     └── flywheel_health.json             │
│       ├── count_fallbacks()                      │
│       │     └── pending_candidates/proposal.json │
│       ├── check_provenance()                     │
│       │     └── pending_candidates/*/            │
│       └── calc_fidelity_score()                  │
│             └── Оценка 0-100 баллов              │
│                                                  │
│  Решение: GO (≥80) / CONDITIONAL (≥60) / NO-GO   │
└─────────────────────────────────────────────────┘
```

## Ежедневные операции

### Утренний чек-лист (выполнять каждый день)

```bash
# 1. Запустить ежедневный отчёт
cd ~/agentforge
bash scripts/soak_daily_report.sh

# 2. Проверить текущий день soak
cat ~/agentforge/soak_start.txt
# Сравнить с текущей датой

# 3. Проверить здоровье flywheel
cat /tmp/agentforge_rust_flywheel/flywheel_health.json | python3 -m json.tool

# 4. Быстрый чек fallback
FALLBACKS=$(grep -rl 'rust_flywheel_fallback' ~/agentforge/pending_candidates/ --include='proposal.json' 2>/dev/null | wc -l)
TOTAL=$(find ~/agentforge/pending_candidates/ -name 'proposal.json' -type f 2>/dev/null | wc -l)
echo "Fallback: $FALLBACKS / $TOTAL proposals"

# 5. Проверить ошибки в логах за последние 24ч
find ~/agentforge/logs/ -name '*.log' -mtime -1 -exec grep -l 'ERROR\|FAIL\|panic' {} \;
```

### Автоматизация через cron

```bash
# Добавить ежедневный отчёт в cron (запуск в 09:00)
crontab -e
# Добавить строку:
0 9 * * * cd /home/eveselove/agentforge && bash scripts/soak_daily_report.sh >> logs/soak_cron.log 2>&1

# Опционально: ночной health-check в 03:00
0 3 * * * cd /home/eveselove/agentforge && bash scripts/soak_health_check.sh >> logs/soak_health_cron.log 2>&1
```

## Расширенные метрики (дополнение к soak_daily_report.sh)

### 1. Тренд score по дням

```bash
#!/bin/bash
# Показать тренд fidelity score за все дни soak
# Использование: bash scripts/soak_trend.sh

REPORTS_DIR="/home/eveselove/agentforge/logs/soak_reports"

echo "=== Тренд Fidelity Score ==="
echo "День | Score | Решение | Дата"
echo "-----|-------|---------|-----"

for f in $(ls -v "$REPORTS_DIR"/soak_day_*.json 2>/dev/null); do
    python3 -c "
import json
with open('$f') as fh:
    r = json.load(fh)
day = r.get('soak_day', '?')
score = r.get('score', {}).get('score', '?')
decision = r.get('decision', '?')
date = r.get('date', '?')[:10]
print(f'{day:>4} | {score:>5} | {decision:<9} | {date}')
"
done
```

### 2. Мониторинг деградации

```bash
#!/bin/bash
# Обнаружение деградации: если score упал >10 пунктов за сутки
# Использование: bash scripts/soak_degradation_check.sh

REPORTS_DIR="/home/eveselove/agentforge/logs/soak_reports"

python3 << 'PYEOF'
import json, glob, sys

files = sorted(glob.glob("/home/eveselove/agentforge/logs/soak_reports/soak_day_*.json"))
if len(files) < 2:
    print("Недостаточно данных для анализа тренда (нужно >= 2 дней)")
    sys.exit(0)

prev = None
alerts = []
for f in files:
    with open(f) as fh:
        r = json.load(fh)
    day = r.get("soak_day", 0)
    score = r.get("score", {}).get("score", 0)
    if prev is not None:
        delta = score - prev["score"]
        if delta < -10:
            alerts.append(f"⚠️ День {day}: score {score} (было {prev['score']}, delta={delta})")
    prev = {"day": day, "score": score}

if alerts:
    print("🚨 ОБНАРУЖЕНА ДЕГРАДАЦИЯ:")
    for a in alerts:
        print(f"  {a}")
else:
    print("✅ Деградации не обнаружено")
PYEOF
```

### 3. Мониторинг ресурсов Erbox

```bash
#!/bin/bash
# Проверка ресурсов хоста во время soak
# Использование: bash scripts/soak_host_check.sh

echo "=== Soak Host Health Check ==="
echo ""

# Память
echo "--- RAM ---"
free -h | head -2

# Диск
echo ""
echo "--- Disk ---"
df -h /home/eveselove | tail -1

# CPU Load
echo ""
echo "--- CPU Load (1m/5m/15m) ---"
uptime | awk -F'load average:' '{print $2}'

# Количество процессов agentforge
echo ""
echo "--- AgentForge Processes ---"
ps aux | grep -c '[a]gentforge'

# GPU (если Erbox)
echo ""
echo "--- GPU ---"
if command -v tegrastats &>/dev/null; then
    timeout 2 tegrastats --interval 1000 2>/dev/null | head -1
elif command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null
else
    echo "GPU info недоступна"
fi

# Размер логов
echo ""
echo "--- Log Size ---"
du -sh /home/eveselove/agentforge/logs/ 2>/dev/null
echo "Pending candidates:"
du -sh /home/eveselove/agentforge/pending_candidates/ 2>/dev/null
```

### 4. Сводка за неделю

```bash
#!/bin/bash
# Еженедельная сводка soak (запускать на 7-й и 14-й день)
# Использование: bash scripts/soak_weekly_summary.sh

REPORTS_DIR="/home/eveselove/agentforge/logs/soak_reports"

python3 << 'PYEOF'
import json, glob

files = sorted(glob.glob("/home/eveselove/agentforge/logs/soak_reports/soak_day_*.json"))
if not files:
    print("Нет отчётов soak")
    exit(0)

scores = []
decisions = {"GO": 0, "CONDITIONAL": 0, "NO-GO": 0}
total_fallbacks = 0
total_proposals = 0

for f in files:
    with open(f) as fh:
        r = json.load(fh)
    s = r.get("score", {}).get("score", 0)
    scores.append(s)
    d = r.get("decision", "NO-GO")
    decisions[d] = decisions.get(d, 0) + 1
    total_fallbacks += r.get("fallbacks", {}).get("proposal_fallbacks", 0)
    total_proposals += r.get("fallbacks", {}).get("total_proposals", 0)

avg_score = sum(scores) / len(scores) if scores else 0
min_score = min(scores) if scores else 0
max_score = max(scores) if scores else 0

print("╔══════════════════════════════════════╗")
print("║   📊 SOAK WEEKLY SUMMARY             ║")
print("╚══════════════════════════════════════╝")
print(f"  Дней в soak: {len(files)}")
print(f"  Средний score: {avg_score:.1f}")
print(f"  Мин/Макс score: {min_score}/{max_score}")
print(f"  Решения: GO={decisions['GO']}, CONDITIONAL={decisions['CONDITIONAL']}, NO-GO={decisions['NO-GO']}")
if total_proposals > 0:
    fb_pct = total_fallbacks / total_proposals * 100
    print(f"  Fallback за период: {total_fallbacks}/{total_proposals} ({fb_pct:.1f}%)")

# Общая рекомендация
if avg_score >= 80 and decisions.get("NO-GO", 0) == 0:
    print("\n  🟢 РЕКОМЕНДАЦИЯ: ГОТОВ К ПРОДАКШЕНУ")
elif avg_score >= 60:
    print("\n  🟡 РЕКОМЕНДАЦИЯ: УСЛОВНО ГОТОВ, нужны улучшения")
else:
    print("\n  🔴 РЕКОМЕНДАЦИЯ: НЕ ГОТОВ, продолжить soak")
PYEOF
```

## Критические алерты

### Что требует немедленного внимания

| Сигнал | Порог | Действие |
|--------|-------|----------|
| Fidelity score < 50 | Критический | Остановить soak, расследовать |
| Fallback > 50% | Высокий | Проверить Rust runner, откат если нужно |
| Provenance < 70% | Высокий | Проверить source-теги в proposals |
| flywheel_health.json не обновляется > 1ч | Средний | Перезапустить runner |
| Диск заполнен > 90% | Критический | Очистить старые логи |
| NO-GO 3 дня подряд | Высокий | Эскалировать, созвать ревью |

### Быстрый откат (если нужно)

```bash
# Немедленный откат на Python flywheel
touch /home/eveselove/agentforge/.disable_rust_flywheel
# ИЛИ
export DISABLE_RUST_FLYWHEEL=1

# Перезапустить воркеры
sudo systemctl restart grok-worker
# XAI-воркеры тоже подхватят новый флаг при рестарте
sudo systemctl restart grok-xai-worker@{1,2}

# Для возврата на Rust:
rm /home/eveselove/agentforge/.disable_rust_flywheel
```

## Структура отчётов

Отчёты сохраняются в `~/agentforge/logs/soak_reports/`:

```
soak_reports/
├── soak_day_1.json
├── soak_day_2.json
├── ...
└── soak_day_14.json
```

### Формат JSON отчёта

```json
{
  "soak_day": 5,
  "soak_duration": 14,
  "soak_status": "active",
  "date": "2026-05-31T12:00:00",
  "soak_start": "2026-05-27",
  "fidelity": {
    "fidelity_ready": true,
    "phase": "production",
    "shadow": false,
    "dry_run": false,
    "avg_success_rate": 0.95,
    "total_high_value_records": 42
  },
  "fallbacks": {
    "proposal_fallbacks": 2,
    "total_proposals": 50,
    "rust_native": 48,
    "log_fallbacks": 0
  },
  "provenance": {
    "provenance_pct": 96.0,
    "total_checked": 50,
    "with_source": 48
  },
  "score": {
    "score": 85,
    "max": 100,
    "breakdown": ["..."]
  },
  "decision": "GO"
}
```

## Финальное GO/NO-GO решение (день 14)

### Критерии для GO:

- [ ] Средний score >= 80 за 14 дней
- [ ] Ни одного NO-GO за последние 7 дней
- [ ] Fallback < 10% за последнюю неделю
- [ ] Provenance >= 90% стабильно
- [ ] Нет критических ошибок в логах
- [ ] Ресурсы хоста стабильны (RAM, диск, CPU)

### Действия после GO:

```bash
# 1. Зафиксировать результаты
bash scripts/soak_weekly_summary.sh > logs/soak_final_report.txt

# 2. Удалить Python fallback код (согласно PHASE4_REMOVAL_PLAN.md)
# 3. Обновить документацию
# 4. Уведомить команду
```

### Действия при NO-GO:

```bash
# 1. Сохранить все отчёты для анализа
tar czf soak_reports_backup.tar.gz logs/soak_reports/

# 2. Откатиться на Python
touch /home/eveselove/agentforge/.disable_rust_flywheel

# 3. Запланировать повторный soak после фикса
# Обновить soak_start.txt после исправлений
```

## Полезные однострочники

```bash
# Быстрый статус soak
echo "Day: $(bash scripts/soak_daily_report.sh --help 2>&1 | head -1 || echo 'run manually')"

# Последний отчёт
ls -t ~/agentforge/logs/soak_reports/*.json | head -1 | xargs python3 -m json.tool

# Все scores одной строкой
for f in ~/agentforge/logs/soak_reports/soak_day_*.json; do
  python3 -c "import json; r=json.load(open('$f')); print(f\"D{r['soak_day']}: {r['score']['score']}\")"
done | paste -sd' '

# Проверить обновляется ли health.json
stat -c '%Y %n' /tmp/agentforge_rust_flywheel/flywheel_health.json
echo "Сейчас: $(date +%s)"
```
