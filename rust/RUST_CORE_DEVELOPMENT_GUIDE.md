# Rust Core Development Guide (Turbo Mode)

**Цель:** Максимально быстро построить полноценную Rust-оркестрацию агентов.

## Текущий статус (31.05.2026)

- `agentforge-core` — есть базовая модель Task + TaskStore trait + InMemory реализация.
- `agentforge-runner` — сильный на Flywheel стороне, слабый на Task Orchestration стороне.
- Есть два xAI ключа (MB2 + MB3) — можно запускать много параллельных агентов.

## Приоритет разработки (по убыванию важности)

1. **Персистентность задач** (JsonFile + SQLite)
2. **CLI для работы с задачами** (create, list, claim, run-worker)
3. **Поддержка нескольких ключей**
4. **HTTP API** (чтобы постепенно заменять Python mcp_server)
5. **Роутинг и мониторинг**

## Правила работы в турбо-режиме

- Бери задачи помеченные `[Rust 100]`.
- Делай маленькие, законченные PR/коммиты.
- Если задача слишком большая — разбей её и создай подзадачи.
- Пиши тесты для всего критичного (TaskStore особенно).
- Используй существующий код в `agentforge-core` как основу.

## Полезные команды

```bash
cd rust
cargo build --release
./target/release/agentforge-runner --help
```

## Как запускать много агентов во время разработки

Используй:
```bash
bash bin/launch_cloud_workers.sh both 3
```

## Контактные точки

- Core: `rust/crates/agentforge-core/src/task.rs`
- Runner: `rust/crates/agentforge-runner/src/main.rs`

Удачи. Летим.
