# TURBO FLYWHEEL 100% — Task Wave (2026-05-31)

**Статус:** Раздано 9 агентам (4 Cloud Grok-4 + 5 Local Grok)  
**Цель:** Довести Rust Flywheel до 100% в максимально короткие сроки  
**Приоритет:** Высокий. Все сложные задачи отдавать облачным агентам.

## Правила раздачи (для агентов и меня)

- **Cloud Grok-4 (особенно reasoning / multi-agent)**: Архитектура, сложный рефакторинг, provenance, безопасность, тяжёлый анализ, улучшение системы задач.
- **Local Grok**: Объёмная работа, мелкие правки, тесты, документация, мелкий рефакторинг.
- **Jules** (когда нужно): Чистое написание кода + PR в целевые репозитории (только код, без деплоя).

---

## Волна задач №1 (Высокий приоритет)

### 1. Усиление provenance в ключевых компонентах
**ID:** (будет назначен)  
**preferred_agent:** grok (cloud)  
**priority:** critical  
**complexity:** complex  
**title:** Жёстко закрепить canonical engine во всех писателях flywheel_health.json и манифестов  
**description:**  
Пройтись по всем местам, где генерируется flywheel_health.json и evaluation manifests.  
Заменить все "MISSING", "rust_flywheel", старые строки на константу из `learning/utils.py` (`RUST_FLYWHEEL_ENGINE`).  
Добавить автоматическую проверку в ключевых скриптах.  
Создать небольшой отчёт о найденных нарушениях.

### 2. Улучшение phase4_pre_removal_audit.sh
**preferred_agent:** grok (cloud)  
**priority:** high  
**complexity:** complex  
**title:** Добавить жёсткие гейты provenance + safety в phase4_pre_removal_audit.sh  
**description:**  
Усилить скрипт `bin/phase4_pre_removal_audit.sh`.  
Добавить обязательные проверки:  
- Все flywheel_health.json используют канонический engine  
- Нет "python" в provenance для чисто Rust шагов  
- Проверка на использование устаревших Python flywheel компонентов  
Сделать так, чтобы аудит падал при нарушениях.

### 3. Автоматическая генерация задач для Flywheel 100
**preferred_agent:** grok (cloud)  
**priority:** high  
**complexity:** complex  
**title:** Создать скрипт/механизм массовой генерации задач для завершения Rust Flywheel 100%  
**description:**  
Сделать инструмент (скрипт или расширение таск-менеджера), который по списку оставшихся пунктов из `RUST_FLYWHEEL_100_SPRINT.md` и `100_PERCENT_READINESS_CHECKLIST.md` автоматически создаёт хорошо сформулированные задачи с правильным `preferred_agent`, `priority`, `complexity` и тегами.  
Это позволит быстро поддерживать очередь в турбо-режиме.

### 4. Улучшение XAI Cloud Worker (умная маршрутизация + стоимость)
**preferred_agent:** grok (cloud)  
**priority:** high  
**complexity:** complex  
**title:** Улучшить grok_xai_worker.sh: умная маршрутизация + защита от перерасхода  
**description:**  
Добавить в `grok_xai_worker.sh`:  
- Учёт примерной стоимости запроса  
- Автоматическое снижение приоритета задач при высоком расходе  
- Возможность ставить "budget" на день  
- Лучшее логирование использованных моделей и токенов  
- Интеграция с таск-менеджером (писать в result использованную модель)

### 5. 14d Soak Monitoring Setup
**preferred_agent:** grok  
**priority:** high  
**complexity:** complex  
**title:** Настроить базовый 14-дневный soak monitoring для Rust Flywheel  
**description:**  
Подготовить инфраструктуру для 14-дневного soak теста чистого Rust Flywheel.  
Создать дашборд/скрипты мониторинга ключевых метрик (fidelity, shadow, composite, error rate, provenance violations).  
Определить, какие метрики должны собираться автоматически.

### 6. Phase 4 Removal Preparation (Python flywheel)
**preferred_agent:** grok (cloud)  
**priority:** high  
**complexity:** complex  
**title:** Подготовить финальный список удаления Python flywheel компонентов (Phase 4)  
**description:**  
На основе текущего состояния сделать точный, проверяемый список файлов/модулей Python flywheel, которые можно безопасно удалить после того, как Rust Flywheel докажет стабильность.  
Разделить на tiers (как в существующих планах).  
Добавить комментарии в код где возможно.

### 7. Улучшение динамического роутера моделей
**preferred_agent:** grok  
**priority:** medium  
**complexity:** medium  
**title:** Улучшить Dynamic Model Router в grok_worker.sh и grok_xai_worker.sh  
**description:**  
Сделать роутер более точным: учитывать не только сложность задачи, но и текущую загрузку облачных vs локальных агентов, историческую успешность моделей на похожих задачах.  
Добавить возможность централизованной конфигурации моделей.

### 8. Документация Turbo Mode
**preferred_agent:** grok  
**priority:** medium  
**complexity:** medium  
**title:** Создать/обновить TURBO_MODE.md с правилами работы в максимальном параллелизме  
**description:**  
Описать текущую конфигурацию (локальные + облачные агенты), как правильно ставить задачи, когда использовать Jules, как мониторить расход xAI, лучшие практики раздачи работы.

### 9-12. Дополнительные задачи (для локальных агентов)

- Проверить и почистить устаревшие бэкапы в `grok_worker.sh` и `jules_worker.sh`.
- Обновить все оставшиеся Python flywheel скрипты деprecation-баннерами (где ещё не сделано).
- Улучшить логирование в XAI worker (добавлять usage stats в task result).
- Создать простой скрипт для быстрого просмотра "что сейчас делают агенты" (по логам и задачам).

---

**Следующие шаги после этой волны:**
- Как только 4-5 задач будут закрыты — генерировать следующую волну.
- Использовать облачных агентов на самые сложные пункты из `RUST_FLYWHEEL_100_SPRINT.md`.
- Регулярно обновлять этот файл.

Готов к раздаче.