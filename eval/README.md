# AgentForge Evaluation Framework

Это фундамент для превращения AgentForge в **frontier-level agentic software engineering system**.

## Философия

> You cannot improve what you cannot measure.

Топ-команды (Anthropic, OpenAI, Cognition и др.) вкладывают огромные ресурсы в evaluation-инфраструктуру. Эта директория — наша версия такого инвестирования.

**Главное пользовательское руководство:** см. **[USAGE.md](./USAGE.md)** — подробный, дружелюбный гайд с примерами, типичными workflow, объяснением регрессий, отчётов и всех команд CLI.

## Текущий статус (Phase 0 → ранняя Phase 1)

- Зрелые схемы (`BenchmarkTask`, `EvaluationResult` и др.)
- Полный CLI (`run`, `run-all`, `report`, `analyze`, `status`, `history`, `insights`, `suggest`, `dashboard`, `list`)
- Примеры реальных высококачественных бенчмарков
- История + детекция регрессий
- Actionable insights + suggestion engine
- Анализ траекторий
- Генерация комбинированных отчётов

## Как пользоваться

**Подробный гайд с примерами команд, объяснением `--wait` / `--concurrency`, историей, регрессиями, insights, suggest и типичными workflow — в [USAGE.md](./USAGE.md).**

### Краткий список команд (CLI)

```bash
python -m agentforge.eval list
python -m agentforge.eval run <bench> --real --wait --report
python -m agentforge.eval run-all --real --wait --concurrency 3
python -m agentforge.eval status
python -m agentforge.eval history [bench] --window 8
python -m agentforge.eval dashboard
python -m agentforge.eval insights
python -m agentforge.eval suggest
python -m agentforge.eval report
python -m agentforge.eval analyze --agent grok
```

Все команды поддерживают `--help`.

### Добавление новых бенчмарков
Просто положите хорошо написанный `.json` в `examples/`. Чем реальнее и болезненнее задача — тем лучше. Подробности и шаблоны — в USAGE.md.

## Regression Detection & Actionable Insights

This is the highest-leverage addition in the current iteration.

### Regression Detection (`regression.py`)
`detect_regressions()` compares recent performance (last N runs) against an older baseline for every benchmark that has sufficient history.

A regression is flagged only when the absolute drop in success rate exceeds the configurable `threshold` (default 15pp).

Key functions:
- `detect_regressions(benchmark_id=None, window=8, baseline_window=20, threshold=0.15)`
- `has_regressions()`
- `format_regression(reg)` — human one-liner

Used automatically by insights & suggestions.

### Actionable Insights & Suggestions
- `insights.py` → `generate_insights()` / `print_insights()`
  - Declining trends from history
  - High infrastructure overhead from trajectories
  - Low RAG utilization
  - **Performance regressions**
  - Safe default when everything looks healthy

- `suggest.py` → `generate_suggestions()` / `print_suggestions()`
  - Turns the above + raw signals into **prioritized, concrete next actions**
  - Critical low-success benchmarks are surfaced as 🔴 High priority
  - Perfect for deciding what to fix or re-run next

These two modules are the "co-pilot" layer on top of raw numbers. They get smarter automatically as you accumulate more `history/*.jsonl` data and trajectories.

CLI entry points (see examples above):
```bash
python -m agentforge.eval insights
python -m agentforge.eval suggest
```

## Текущий уровень качества (Phase 0 → ранняя Phase 1)

- Отличные, хорошо документированные схемы (`BenchmarkTask`, `EvaluationResult` и др.)
- Полноценный CLI со всеми ключевыми возможностями
- **8+ высококачественных реальных бенчмарков** из настоящей истории проекта (lancedb, crawlers, рефакторинги Rust и т.д.)
- Продольная история (append-only JSONL) + автоматическое определение трендов
- Детекция регрессий + генерация actionable insights и приоритизированных рекомендаций
- Анализ траекторий + комбинированные отчёты с Health Score
- Готово к регулярному использованию в разработке и CI

Подробно о возможностях, типичных сценариях использования и лучших практиках — в **[USAGE.md](./USAGE.md)**.

См. также дорожную карту: `AGENTFORGE_FRONTIER_ROADMAP.md`.

## Принципы хороших бенчмарк-задач

- Реальная работа из актуального кодбейза (никаких toy problems)
- Чёткая объективная верификация (тесты / cargo check / golden diff >> LLM judge)
- Воспроизводимое окружение
- Разметка по сложности, категории и требуемым навыкам
- Реалистичная оценка времени

Подробные рекомендации и примеры структуры JSON — в разделе «Как добавлять свои бенчмарки» файла [USAGE.md](./USAGE.md).

---

**Для повседневной работы и глубокого понимания используйте [USAGE.md](./USAGE.md)** — это основной, постоянно актуальный гайд с примерами, workflow и объяснениями всех возможностей фреймворка.
