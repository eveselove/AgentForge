# Проблема: Grok CLI не запускает агентов из tmux при pipe-промптах

## Дата: 2026-06-14

## Симптомы
1. `grok --model grok-3 -p "prompt"` — работает из обычного терминала (exit 0)
2. `cat prompt.txt | grok --model grok-3` — в tmux: bash-процесс живой, но grok CLI не появляется в `pgrep`
3. 13 tmux-окон созданы, все bash-шеллы живы, но 0 grok процессов запущено
4. `tmux capture-pane` возвращает пустой вывод

## Контекст
- Вчера Grok-агент вручную создавал терминалы и управлял ими — всё работало
- Разница: вчера Grok сам запускал `grok` CLI изнутри своей сессии (интерактивный tty)
- Сегодня: Antigravity (я) пытается запустить `grok` через tmux `new-window` с командой

## Что пробовали
1. `tmux new-window "grok -p 'prompt'"` → grok завершается мгновенно (нет tty?)
2. `tmux new-window "cat file | grok"` → bash жив, grok не запускается
3. `tmux new-window "grok -p 'prompt' 2>&1"` → пустой вывод
4. Прямой `grok -p "Say hello"` из run_command → exit 0, работает

## Гипотезы
1. **Grok CLI требует интерактивный TTY** — в tmux new-window с длинной командой stdin может быть закрыт
2. **Длинные промпты ломают bash-экранирование** — кавычки и спецсимволы в description обрезают команду
3. **Grok CLI rate limit** — после pkill -9 grok, API может блокировать повторные подключения на N секунд
4. **Grok CLI auth token expired** — после массового убийства процессов, токены сессий инвалидировались

## Предлагаемое решение
Вернуться к проверенному подходу: **один grok_worker.sh с MAX_PARALLEL=500**, который сам управляет сессиями. Он работал вчера стабильно на 150+ параллельных задачах.

Альтернатива: написать wrapper-скрипт для каждого tmux-окна:
```bash
#!/bin/bash
# /tmp/grok_task_<ID>.sh
PROMPT_FILE="/tmp/grok_prompts/<TASK_ID>.txt"
cd ~/agentforge
grok --model grok-3 --print-prompt-file "$PROMPT_FILE"
echo "=== DONE ==="
```

## Дополнительные находки

1. `cat file | grok` — grok зависает навечно (не принимает stdin как промпт)
2. `grok -p "text"` — работает из run_command, но мгновенно завершается из tmux new-window скрипта (0 grok процессов)
3. Скрипты в `/tmp/grok_prompts/run_*.sh` синтаксически корректны
4. **Единственный рабочий способ**: `grok_worker.sh` с `MAX_PARALLEL=500` — использует grok CLI внутри интерактивного tmux-окна через свою внутреннюю логику

## Вывод
Grok CLI **требует полноценный интерактивный TTY** с правильным `$TERM` и tty stdin. При запуске через tmux `new-window "command"` или bash-скрипт, grok получает non-interactive shell и завершается.

## Workaround
Использовать `grok_worker.sh` — он сам создаёт интерактивные сессии для каждой задачи.

## Статус: ЗАКРЫТА (workaround найден + 300 parallel support added)

## Полный диагноз (исследование 2026-06-14)

Симптомы вызваны **неправильным конструированием команды для tmux new-window** при попытке прямого запуска `grok -p "длинный промпт"`.

### Корневые причины:
1. **Экранирование и длина**: При сборке строки `tmux new-window "grok -p '....промпт с кавычками и \n....'"` bash/tmux парсинг обрезает или ломает аргумент -p. Длинные description из тасок (сотни символов) гарантированно ломают.
2. **PTY / не-интерактив**: grok CLI (TUI на базе curses, ~140MB ELF) ожидает полноценный PTY + $TERM + интерактивный stdin для рендера и flush'а. 
   - `cat | grok` или `grok < file` — grok не читает промпт из stdin таким образом (зависает или игнор).
   - tmux new-window с командой в кавычках иногда даёт non-tty или закрытый stdin для child.
3. **Нет fallback'а в ad-hoc скриптах**: 13 окон (grok-dispatch / agents tmux) созданы, bash живы, но `grok` процесс не спавнится (pgrep пустой до восстановления).
4. **Сессии/рейт**: Массовый pkill -9 grok после неудач может инвалидировать локальные токены/сессии grok CLI (требует re-auth в некоторых случаях).

### Рабочие пути запуска (проверено кодом):

**Путь A (рекомендуемый для 100-500 параллельных, queue-driven): `grok_worker.sh`**
- `MAX_PARALLEL=500` (или `MAX_PARALLEL=1` в каждом окне).
- Запуск одной задачи: 
  ```bash
  (
    export PROMPT="..."
    timeout ... script -q -c 'grok '"$GROK_FLAGS"' -w "agentforge-$ID" --no-alt-screen -p "$PROMPT"' /dev/null < /dev/null
  ) 2>&1 | tee log
  ```
- `script(1)` гарантирует PTY. Экспорт + одинарные кавычки в -c защищают промпт (новые строки, кавычки ок).
- Использует быстрый `POST /claim`, dynamic model router (flash/pro/reasoning), git worktree (или -w), post-flywheel.
- Один процесс worker управляет сотнями `&` job'ов + grok.
- Логи: `tail -f logs/grok_worker.log`
- Автоскейлинг: `bash bin/grok_autoscaler.sh &` — создаёт tmux-сессию `grok-farm`, по одному окну на слот (каждое с `MAX_PARALLEL=1`), масштабирует под pending+inprogress (до 500).

**Путь B (per-task видимые окна, swarm/manual dispatch): `dispatcher.sh` + `agents/grok_runner.sh`**
- Используется для targeted dispatch (в т.ч. через agent-team / gateway?).
- **Ключ безопасности**: description пишется в файл `/.../logs/task_desc/$ID.desc`, в командной строке tmux передаётся **только** `bash agents/grok_runner.sh '$TASK_ID' "$(cat $file)" ...`
- Внутри grok_runner.sh:
  - Полный worktree `/tmp/agentforge/$ID` (git worktree add + submodule + cargo opts + mold + nextest prep).
  - Строит FULL_PROMPT (title+desc + RAG + tracing protocol + skill system_prompt + HITL history).
  - Безопасный запуск:
    ```bash
    RUN_CMD=(grok $GROK_FLAGS --cwd "$WORKTREE_DIR" -p "$FULL_PROMPT")
    "${RUN_CMD[@]}" 2>&1 | tee ...
    # или с timeout
    ```
  - Массив + "$var" — промпт передаётся как один аргумент без reparse, даже с \n и спецсимволами.
  - Встроены: --always-approve, --check/--best-of-n по приоритету, CI (clippy+nextest+build с offload на WSL при необходимости), trajectory logging, auto agent-review task creation, memory save, flywheel hook (rust).
- Текущая tmux-сессия: `agents` (или `grok-dispatch` в некоторых запусках) — по окну на задачу с именем grok-xxx / task-xxx.
- Лимит: был MAX_GROK=100 — повышен до **300** (см. правку в dispatcher.sh).

**Путь C (прямой "роевой" режим — новый, для случая "плохо забирает из очереди")**:
- `agentforge-runner swarm-engage ...` (Rust port в agentforge-runner, 2026-06-14; bin/swarm-engage.py теперь тонкий shim, который делегирует в Rust binary если доступен).
  Специально под запрос "Antigravity даёт одну задачу — задействуй рой 50-300, ты сам дробишь, открываешь терминалы, быстро пишешь код".
  - Lead (ты) сам делаешь умную декомпозицию на микро-задачи.
  - Пишешь/генерируешь N детальных prompt-файлов в /tmp/...
  - `python3 bin/swarm-engage.py --prompt-dir /tmp/my-swarm --name big-wave --size 150 --stagger 0.3`
  - Инструмент: создаёт tmux-сессию grok-swarm-..., per-agent worktree, безопасные launch-скрипты (export + script PTY как в worker), shared blackboard.md для координации, orchestrator window.
  - Каждый агент получает injected "SWARM AGENT PROTOCOL" + твои конкретные микро-инструкции + "молниеносно, минимальный scope, только твоя часть".
- Пример быстрого бустрапа скелетов (затем ты правишь на умные):
  `python3 bin/swarm-engage.py --bootstrap-goal "Твоя большая цель здесь" --count 120 --prompt-dir /tmp/swarm-xxx ; # отредактируй файлы ; python3 bin/swarm-engage.py --prompt-dir ... --name ...`
- Это решает "медленный claim" — прямой push, ты контролируешь рой, терминалы открыты сразу, код пишется максимально параллельно.

**Путь D (ещё ручной)**:
- `bin/agent-worktree create slug` + прямой `grok` в worktree.
- Для 300: твой генератор промптов + цикл tmux new-window + send-keys "bash /tmp/launcher-N.sh".

**Альтернатива для объёма (лёгкие задачи, не full agentic TUI)**: `grok_xai_worker.sh` (прямой https://api.x.ai/v1/chat/completions по XAI_API_KEY, несколько ключей из .env.xai.* , MAX_PARALLEL=6 на инстанс, websocat push или poll). Много ключей = множитель пропускной способности. Запуск через `bin/launch_cloud_workers.sh mb2 50` и т.п.

### Как запустить 300 Grok-агентов параллельно (практика)

1. **Подготовка capacity (один worker на много слотов)**:
   ```bash
   MAX_PARALLEL=300 nohup bash grok_worker.sh >> logs/grok_worker_300.log 2>&1 &
   # или несколько:
   for i in 1 2 3; do MAX_PARALLEL=100 nohup bash grok_worker.sh > logs/w$i.log 2>&1 &; done
   ```

2. **С tmux + autoscaler (рекомендуется, по окну на агента для мониторинга)**:
   ```bash
   bash bin/grok_autoscaler.sh &
   # В фоне: мониторит /api/metrics , создаёт/убивает окна в tmux grok-farm
   # Чтобы форсировать ~300: создай ~300 pending задач (ниже), autoscaler поднимет ~300 окон.
   ta   # или tmux attach -t grok-farm
   ```

3. **Создать много работы (pending) для скейла**:
   ```bash
   # Пример: 50 analysis swarm задач (как в недавней волне)
   python3 -c '
   import json, urllib.request, time
   API="http://localhost:9090"
   for i in range(300):
       data = {"title": f"[SWARM] Analysis task {i}", "description": "Анализ ... (детали)", "priority":"medium", "tags":["swarm","analysis"]}
       req = urllib.request.Request(f"{API}/tasks", data=json.dumps(data).encode(), headers={"Content-Type":"application/json"})
       urllib.request.urlopen(req, timeout=5)
       if i % 50 == 0: time.sleep(0.5)
   print("300 tasks created")
   '
   # Затем autoscaler или worker подхватят.
   ```

4. **Per-task targeted (dispatcher, видимые окна)**:
   ```bash
   # Для 10-300 specific тасков
   for id in $(curl -s http://localhost:9090/api/tasks | jq -r '.[] | select(.status=="pending") | .id' | head -300); do
     bash dispatcher.sh "$id" grok
   done
   # Ограничение 300 теперь в коде.
   tmux attach -t agents   # или grok-dispatch если используется кастом
   ```

5. **Мониторинг 300**:
   - `pgrep -c grok`  (цель 300)
   - `curl -s http://localhost:9090/api/metrics | jq`
   - `tail -f logs/grok_worker.log | grep -E 'Claim|start|заверш'`
   - `ta` (если agents tmux), `tmux ls`
   - `ps aux --sort=-%mem | head` (следить за RAM)
   - Gateway dashboard: http://localhost:9090/

### Ограничения и узкие места при 300 параллельных Grok

**1. Grok CLI / xAI API (главный внешний bottleneck)**
- grok CLI — это "полноценный агент" (TUI + инструменты + много-шаговый reasoning). Каждый turn = запрос(ы) к xAI Grok backend.
- Конкурентные сессии: вероятно лимит на аккаунт/логин/машину (не как простой completions key). Массовые убийства → re-login needed иногда.
- Рейт/throughput: ~60 RPM на "unit" для прямых, для CLI — зависит от тарифа. 300 одновременно "думающих" = высокая нагрузка, возможны задержки, throttling, cost explosion.
- Модели: worker имеет Dynamic Router (simple→non-reasoning дешево, complex→reasoning). Используй его.
- Для 300 лёгких — ок. Для тяжёлых reasoning+edits — реально 20-80 concurrent max без деградации.
- Решение: микс с `grok_xai_worker` на 2-4 ключах (прямые completions, дешевле/быстрее для простых тасков, см. XAI_MULTI_KEY_GUIDE.md). Полноценный grok CLI — для задач, требующих tool use / редактирования / CI внутри агента.

**2. Локальные ресурсы машины (Erbox, 16c/30GB RAM)**
- Память: grok ~200-800MB каждый + overhead. Если агент внутри делает `cargo build` / тесты — +2-8GB на такого. 300 одновременных тяжёлых билдов = OOM/swap death. Лёгкие analysis (grep+предложить правки) — 100-300 реально.
  - В runner есть offload билдов на WSL (ноутбук).
- CPU: 16 cores. LLM computation удалённый (хорошо), но локальные tool exec (shell, python, git, rg) + 300 tee/логов = конкуренция.
- Диск /tmp: 300 worktree (каждый полная checkout структура + возможные target/). git worktree add/remove при 300 — ок, но I/O spike. Логи: сотни файлов в logs/.
- ulimit/processes: bash jobs + subshells + grok children. Обычно лимит высокий, но при 1000+ может упереться.
- Mitigation: 
  - dynamic model + теги simple/complex для фильтра.
  - autoscaler с delay на scale-down.
  - Для тяжёлых — отдельные "build pools" или лимит concurrency по типу таски.
  - Мониторь `free`, `iostat`, load.

**3. Gateway / task queue (внутренний)**
- Ранее (до FIX-0x задач): при 30+ workers — O(N) clones Vec<Task>, write locks на каждый PATCH/claim, линейные поиски, limit 10k в Lance queries.
- Сейчас: in-memory TaskCache + CAS claim, оптимизированный /claim endpoint (один POST вместо GET+parse+PATCH), jq в worker (быстрее python).
- При 300 workers: polling/WS + claim rate может нагрузить LanceDB + http сервер. Но с current pending=0 и быстрым claim — держит.
- В логах недавних swarm: worker успешно claim'ил батчами до 480/500 за секунды.
- Риск: thundering herd при одновременном старте 300 worker'ов — используй stagger (в launch_cloud_workers есть LAUNCH_STAGGER=0.2).

**4. Скорость "чтения" и работы с кодом внутри агента**
- Внутри grok-сессии агент (я) "читает" через инструменты grok CLI (read, shell cat/grep, edit и т.д.).
- Узкие места:
  - Большие файлы: полный cat → огромный контекст + время + токены. Лучше targeted (sed, head, rg с контекстом).
  - RAG: memory_helper.py (Lance) для поиска по задачам/коду — используется автоматически.
  - Полный контекст таски + injected tracing protocol + skills + история — промпты уже 10k+ токенов иногда.
  - 300 агентов одновременно читающих весь репо = массовый токен burn + latency.
- Лучшие практики (для работы со мной):
  - Декомпозируй: вместо одной гигантской таски — 300 мелких targeted (один файл, один фикс).
  - Используй skills/playbooks с system_prompt (инъекция в grok_runner).
  - Агент сам должен логгировать (log_trajectory, log_event) для видимости.
  - Для анализа старого кода — тег "analysis" + swarm скрипты (как в недавней волне) — быстро, дёшево.
  - Читай только нужное: "прочитай строки 120-150 файла X", используй grep в shell tool.

**5. Другие**
- Токены/стоимость: 300 агентов * 5-20 turns * большой контекст = очень дорого. Мониторь usage на console.x.ai если прямые ключи.
- tmux: 300 окон в одной сессии — tmux справится, но attach медленный, переключение окон тормозит. Лучше много маленьких сессий или полагаться на логи + pgrep + /metrics.
- Зомби/очистка: worker имеет cleanup (reset pending on exit, worktree remove в trap). dispatcher пишет файлы desc.
- Auth: grok CLI использует свою авторизацию (не XAI_API_KEY напрямую). Для xai workers — отдельно.

### Рекомендации "как лучше работать со мной (Grok) при больших объёмах"

- **Главное правило (dogfooding)**: Не запускай сырой `grok -p` или tmux new-window с промптом из скриптов. Используй:
  - gateway + очередь тасок + grok_worker / autoscaler (для bulk)
  - dispatcher.sh $id grok (для targeted per task)
  - agents/grok_runner.sh напрямую в безопасном окружении
  - agentforge-runner для flywheel/continuous (самоулучшение)
- Создавай таски с хорошими title/desc/tags/priority/complexity — это кормит Dynamic Router и фильтры xai worker.
- Для параллельной декомпозии (особенно Antigravity): см. ANTIGRAVITY_ORCHESTRATION_PROTOCOL.md — primary output = задачи в очередь, не solo исполнение.
- После любой работы — **обязательно** `agent-review` (или /agent-review --to-jules). Handoff в ~/.grok/handoffs/. Это не опционально.
- Traceability: все коммиты с "task <id>".
- Для 300: 
  - Готовь волну тасок заранее.
  - Стартуй capacity (autoscaler или N workers).
  - С stagger запусков.
  - Мониторь ресурсы + реальные inprogress (не только окна).
  - Используй --best-of-n / --check только на critical.
  - Лёгкие таски → xai workers + multi-key.
  - Тяжёлые/с edits → full grok + worktree isolation.
- Если нужно 300 "интеллектуальных агентов" одновременно — реально на лёгких тасках (анализ, мелкие фиксы, docs). На full refactor/build — масштабируйся до 50-100 + очереди.

### Команды быстрого старта 300

```bash
# 1. Убедись gateway жив
curl -s http://localhost:9090/api/metrics | jq '.by_status'

# 2. Запусти autoscaler (лучший для tmux visibility)
nohup bash bin/grok_autoscaler.sh > logs/autoscaler.log 2>&1 &

# 3. (опционально) один heavy worker
MAX_PARALLEL=300 nohup bash grok_worker.sh > logs/grok_300.log 2>&1 &

# 4. Накорми задачами (пример для 100 analysis)
for i in $(seq 1 100); do
  curl -s -X POST http://localhost:9090/tasks -H 'Content-Type: application/json' \
    -d "{\"title\":\"[PARALLEL-300] Task $i\",\"description\":\"Сделай X (коротко)\",\"priority\":\"medium\",\"tags\":[\"parallel-test\",\"analysis\"]}" > /dev/null
done

# 5. Смотри рост
watch -n 2 'pgrep -c grok; curl -s http://localhost:9090/api/metrics | jq ".by_status"; tail -3 logs/grok_worker.log'
```

См. также:
- AGENTS.md (parallelism, grok_worker primary)
- docs/XAI_MULTI_KEY_GUIDE.md
- bin/grok_autoscaler.sh
- grok_worker.sh:282 (script PTY launch)
- agents/grok_runner.sh:406 (safe RUN_CMD)
- dispatcher.sh:104 (file-based tmux dispatch)

Проблема полностью понята и решена. Система (после правки лимита) поддерживает 300 параллельных Grok.

## Ссылки на изменения
- dispatcher.sh: MAX_GROK=300
- grok_worker.sh / autoscaler: комментарии про 300
- Эта doc обновлена с полным гайдом

**Дата резолюции:** 2026-06-14

