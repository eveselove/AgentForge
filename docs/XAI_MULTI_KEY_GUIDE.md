# 🔑 Руководство по работе с двумя xAI ключами

> Версия: 1.0 | Дата: 2026-05-31
> Автор: AgentForge / Antigravity

## Обзор

AgentForge поддерживает работу с **несколькими xAI API ключами одновременно**.
Это позволяет:
- Увеличить пропускную способность (rate-limit на ключ ~60 RPM)
- Распределить нагрузку между аккаунтами
- Обеспечить отказоустойчивость (если один ключ заблокирован)

## Архитектура

```
┌──────────────┐    ┌─────────────────────────┐
│ Task Queue   │◄───│ AgentForge API :8080     │
│ (pending)    │    └─────────────────────────┘
└──┬───────┬───┘              ▲
   │       │                  │ PATCH /tasks/{id}
   ▼       ▼                  │
┌──────┐ ┌──────┐    ┌───────┴───────┐
│ XAI  │ │ XAI  │    │ Результаты    │
│ Key1 │ │ Key2 │    │ задач         │
│ @1   │ │ @2   │    └───────────────┘
└──────┘ └──────┘
  grok-xai-worker@1    grok-xai-worker@2
```

Каждый systemd-инстанс `grok-xai-worker@N` — это отдельный процесс,
который использует **свой `.env.xai`** файл (или разные env-файлы).

## Настройка двух ключей

### Шаг 1: Создать env-файлы для каждого ключа

```bash
# Ключ 1 — основной
cat > /home/eveselove/agentforge/.env.xai.key1 << 'EOF'
XAI_API_KEY="xai-ВАША_ПЕРВАЯ_xAI_КЛЮЧ"
XAI_MIN_COMPLEXITY=complex
XAI_FORCE_MULTI_AGENT=0
EOF

# Ключ 2 — дополнительный
cat > /home/eveselove/agentforge/.env.xai.key2 << 'EOF'
XAI_API_KEY="xai-ВАША_ВТОРАЯ_xAI_КЛЮЧ"
XAI_MIN_COMPLEXITY=high
XAI_FORCE_MULTI_AGENT=0
EOF
```

> ⚠️ **Важно:** Используйте разные `XAI_MIN_COMPLEXITY` для балансировки:
> - Ключ 1 (`complex`) — только самые тяжёлые задачи
> - Ключ 2 (`high`) — задачи высокой и критической сложности

### Шаг 2: Настроить systemd template для разных ключей

Создайте два override-файла:

```bash
# Для инстанса @1 (ключ 1)
sudo mkdir -p /etc/systemd/system/grok-xai-worker@1.service.d
sudo tee /etc/systemd/system/grok-xai-worker@1.service.d/override.conf << 'EOF'
[Service]
EnvironmentFile=/home/eveselove/agentforge/.env.xai.key1
EOF

# Для инстанса @2 (ключ 2)
sudo mkdir -p /etc/systemd/system/grok-xai-worker@2.service.d
sudo tee /etc/systemd/system/grok-xai-worker@2.service.d/override.conf << 'EOF'
[Service]
EnvironmentFile=/home/eveselove/agentforge/.env.xai.key2
EOF
```

### Шаг 3: Запустить оба инстанса

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now grok-xai-worker@1
sudo systemctl enable --now grok-xai-worker@2
```

### Альтернатива: Запуск вручную (без systemd)

```bash
# Терминал 1 — ключ 1
export XAI_API_KEY="xai-ПЕРВЫЙ_КЛЮЧ"
export XAI_MIN_COMPLEXITY=complex
nohup bash ~/agentforge/grok_xai_worker.sh >> ~/agentforge/logs/xai_key1.log 2>&1 &

# Терминал 2 — ключ 2
export XAI_API_KEY="xai-ВТОРОЙ_КЛЮЧ"
export XAI_MIN_COMPLEXITY=high
nohup bash ~/agentforge/grok_xai_worker.sh >> ~/agentforge/logs/xai_key2.log 2>&1 &
```

## Рекомендуемое количество воркеров

| Сценарий | Ключ 1 | Ключ 2 | Итого воркеров | MAX_PARALLEL | Примечание |
|----------|--------|--------|----------------|--------------|------------|
| **Экономный** | 1 инстанс, complex | — | 1 | 3 | Один ключ, только сложные задачи |
| **Стандартный** | 1 инстанс, complex | 1 инстанс, high | 2 | 6 каждый | Баланс цена/скорость |
| **Турбо** | 2 инстанса, complex | 1 инстанс, high | 3 | 6 каждый | Максимальная пропускная способность |
| **Full Blast** | 2 инстанса, complex+MA | 2 инстанса, high | 4 | 6 каждый | Когда нужен максимум мощности |

### Ограничения xAI API

- **Rate limit:** ~60 запросов в минуту на ключ (стандартный тариф)
- **Модели:** `grok-4.20-0309-non-reasoning`, `grok-4.20-0309-reasoning`, `grok-4.20-multi-agent-0309`
- **Макс. токены:** 12000 (настраивается в `call_xai()`)
- **Таймаут задачи:** 600 секунд (по умолчанию в `TASK_TIMEOUT`)

### Формула расчёта воркеров

```
MAX_RPM_per_key ≈ 60
Среднее_время_запроса ≈ 30-120 сек
Параллельность_на_ключ = MAX_RPM_per_key * Среднее_время / 60

# При среднем запросе 60 сек:
# 60 * 60 / 60 = 60 параллельных задач (теоретический максимум)
# Реально рекомендуется: 3-6 на ключ (с запасом на ретраи)
```

## Мониторинг расхода

### Проверка логов

```bash
# Сколько задач обработал каждый воркер
grep -c "завершена" ~/agentforge/logs/grok_xai_worker.log

# Ошибки API
grep "XAI_ERROR\|XAI error" ~/agentforge/logs/grok_xai_worker.log | tail -10

# Сколько задач в работе сейчас
curl -s http://localhost:8080/tasks | python3 -c "
import json, sys
tasks = json.load(sys.stdin)
by_status = {}
for t in tasks:
    s = t.get('status','unknown')
    by_status[s] = by_status.get(s, 0) + 1
for s, c in sorted(by_status.items()):
    print(f'  {s}: {c}')
"
```

### Скрипт мониторинга расхода (рекомендуется в cron)

```bash
#!/bin/bash
# Быстрый чек расхода xAI ключей за последний час
# Использование: bash scripts/xai_usage_check.sh

LOG="/home/eveselove/agentforge/logs/grok_xai_worker.log"
HOUR_AGO=$(date -d '1 hour ago' '+%H:%M')

echo "=== xAI Usage Report (последний час) ==="
echo "Успешных:"
grep "завершена" "$LOG" | awk -v t="$HOUR_AGO" '$2 >= t' | wc -l
echo "Ошибок:"
grep "XAI_ERROR" "$LOG" | awk -v t="$HOUR_AGO" '$2 >= t' | wc -l
echo "Моделей использовано:"
grep "XAI" "$LOG" | grep "model=" | awk -v t="$HOUR_AGO" '$2 >= t' | grep -oP 'model=\K\S+' | sort | uniq -c | sort -rn
```

### Мониторинг через xAI Dashboard

xAI предоставляет дашборд использования:
- **URL:** https://console.x.ai/
- Раздел **Usage** — отображает расход по каждому API ключу
- Рекомендуется проверять расход **ежедневно** при двух ключах

### Алерты (настройка уведомлений)

Добавьте в cron проверку ошибок:

```bash
# Каждые 30 минут проверяем ошибки
*/30 * * * * bash -c 'ERRORS=$(grep -c "XAI_ERROR" ~/agentforge/logs/grok_xai_worker.log 2>/dev/null || echo 0); [ "$ERRORS" -gt 10 ] && echo "XAI errors: $ERRORS" >> ~/agentforge/logs/alerts.log'
```

## Переменные окружения

| Переменная | Описание | Значение по умолчанию |
|---|---|---|
| `XAI_API_KEY` | API ключ xAI | (обязательно) |
| `XAI_MIN_COMPLEXITY` | Минимальная сложность задач | `complex` |
| `XAI_FORCE_MULTI_AGENT` | Всегда multi-agent модель | `0` |
| `MAX_PARALLEL` | Макс. параллельных задач | `6` |
| `POLL_INTERVAL` | Интервал опроса очереди (сек) | `10` |
| `TASK_TIMEOUT` | Таймаут задачи (сек) | `600` |

## Безопасность ключей

1. **Никогда** не коммитьте ключи в Git
2. Храните ключи в `.env.xai*` файлах (добавлены в `.gitignore`)
3. Используйте `chmod 600 .env.xai*` для ограничения доступа
4. При утечке — немедленно ревокните ключ на https://console.x.ai/

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| `XAI_API_KEY не установлен` | Проверь EnvironmentFile в systemd или export перед запуском |
| `rate_limit_exceeded` | Уменьши MAX_PARALLEL до 3, увеличь POLL_INTERVAL до 15 |
| `invalid_api_key` | Проверь ключ на https://console.x.ai/, перегенерируй |
| Воркер не берёт задачи | Проверь XAI_MIN_COMPLEXITY — если `complex`, простые задачи пропускаются |
| Два воркера берут одну задачу | Нормально: первый делает dispatch, второй получит 409 конфликт |

## Полезные команды

```bash
# Статус воркеров
systemctl status grok-xai-worker@{1,2}

# Логи в реальном времени
journalctl -u grok-xai-worker@1 -f
journalctl -u grok-xai-worker@2 -f

# Перезапуск при проблемах
sudo systemctl restart grok-xai-worker@{1,2}

# Остановка всех xAI воркеров
sudo systemctl stop grok-xai-worker@{1,2}

# Проверка что оба ключа работают
for i in 1 2; do
  KEY=$(grep XAI_API_KEY /home/eveselove/agentforge/.env.xai.key$i | cut -d= -f2 | tr -d '"')
  echo "Key $i: $(echo $KEY | head -c 10)..."
  curl -s https://api.x.ai/v1/models -H "Authorization: Bearer $KEY" | \
    python3 -c "import json,sys; d=json.load(sys.stdin); print('  OK:', len(d.get('data',[])), 'models') if 'data' in d else print('  ERROR:', d.get('error','unknown'))"
done
```
