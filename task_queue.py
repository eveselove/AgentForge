"""
DEPRECATED — MOVING TO RUST ONLY
=================================
This file is part of the legacy Python task management layer.

As of 2026-05-31 we are executing a full migration to Rust-only operation.
The long-term goal is to have `agentforge-runner` (or a small set of Rust services)
handle task ingestion, dispatching, and the full agent conveyor.

See:
- RUST_ONLY_MIGRATION_PLAN.md
- docs/LANCE_TASK_STORE_MIGRATION_PLAN.md (we are replacing SQLite task storage with LanceDB)

This Python implementation is kept temporarily for compatibility during the transition.
New development should target the Rust side.

Last major update before full deprecation effort: 2026-05-31
"""

"""
AgentForge Task Queue Server (Legacy)
=====================================
Сервер очереди задач для оркестрации AI-агентов.
Использует FastAPI + aiosqlite для асинхронного хранения задач.
Биндится на 0.0.0.0:8080

Агенты:
  - antigravity: Архитектор, сложные задачи, анализ, code review
  - grok: Быстрый мультиагентный исполнитель (включая Rust, серверные задачи)
  - jules: Асинхронный фоновый агент (GitHub PRs)
"""

import uuid
import subprocess
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import json as json_module
import asyncio

import aiosqlite
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# === Константы ===
DB_PATH = os.path.expanduser("~/agentforge/tasks.db")
DISPATCHER_PATH = os.path.expanduser("~/agentforge/dispatcher.sh")
SKILLS_DIR = os.path.expanduser("~/agentforge/skills")

# === Перечисления для валидации ===

class Priority(str, Enum):
    """Приоритет задачи"""
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

class Complexity(str, Enum):
    """Сложность задачи"""
    simple = "simple"
    medium = "medium"
    complex = "complex"

class PreferredAgent(str, Enum):
    """Предпочтительный агент для выполнения"""
    antigravity = "antigravity"
    grok = "grok"
    jules = "jules"
    auto = "auto"

class TaskStatus(str, Enum):
    """Статус задачи"""
    pending = "pending"
    dispatched = "dispatched"
    in_progress = "in_progress"
    review = "review"
    done = "done"
    failed = "failed"

# === Pydantic модели ===

class TaskCreate(BaseModel):
    """Модель для создания новой задачи"""
    title: str = Field(..., description="Название задачи")
    description: str = Field("", description="Подробное описание задачи")
    priority: Priority = Field(Priority.medium, description="Приоритет: low/medium/high/critical")
    complexity: Complexity = Field(Complexity.medium, description="Сложность: simple/medium/complex")
    preferred_agent: PreferredAgent = Field(PreferredAgent.auto, description="Предпочтительный агент")
    tags: list[str] = Field(default_factory=list, description="Теги задачи для маршрутизации")
    skill: Optional[str] = Field(None, description="Явный skill/playbook (иначе авто-подбор по required_tags)")

class TaskReject(BaseModel):
    """Модель отклонения задачи пользователем"""
    feedback: str = Field(..., description="Причина отклонения выполнения (фидбек)")

class TaskUpdate(BaseModel):
    """Модель для обновления задачи"""
    status: Optional[TaskStatus] = None
    result: Optional[str] = None
    assigned_agent: Optional[str] = None
    duration_seconds: Optional[float] = None
    skill: Optional[str] = None
    retry_count: Optional[int] = None
    tokens_used: Optional[int] = None
    cost_usd: Optional[float] = None

class TaskResponse(BaseModel):
    """Модель ответа с данными задачи"""
    id: str
    title: str
    description: str
    priority: str
    complexity: str
    preferred_agent: str
    status: str
    assigned_agent: Optional[str]
    result: Optional[str]
    git_branch: Optional[str]
    created_at: str
    updated_at: str
    tags: list[str]
    duration_seconds: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    skill: Optional[str] = None
    retry_count: Optional[int] = 0
    tokens_used: Optional[int] = 0
    cost_usd: Optional[float] = 0.0

class CheckpointCreate(BaseModel):
    """Модель для создания чекпоинта промежуточного состояния"""
    state: dict = Field(default_factory=dict, description="Промежуточное состояние задачи (JSON)")
    step_index: int = Field(0, description="Индекс текущего шага выполнения")
    message: str = Field("", description="Сообщение/комментарий к чекпоинту")


class WebhookRegister(BaseModel):
    """Модель для регистрации вебхука"""
    url: str = Field(..., description="URL для отправки уведомлений (POST)")
    events: list[str] = Field(default_factory=lambda: ["status_change"], description="Типы событий: status_change, task_created, task_completed")


class SkillCapture(BaseModel):
    """Модель для self-expansion: автоматического захвата нового YAML skill/playbook агентом"""
    name: str = Field(..., min_length=2, max_length=64, description="Короткое kebab-case имя скилла (напр. parse-acme-api)")
    description: str = Field(..., min_length=10, description="Краткое описание назначения скилла (для авто-подбора)")
    system_prompt: str = Field(..., min_length=50, description="Полный system prompt, который будет инжектиться в задачи с подходящими тегами")
    required_tags: list[str] = Field(default_factory=list, description="Теги, по которым этот скилл будет автоматически выбираться (select_skill)")
    ci_checks: list[str] = Field(default_factory=list, description="Список shell-команд для CI-проверок после выполнения задач с этим скиллом")
    timeout: int = Field(900, ge=60, le=7200, description="Таймаут выполнения задачи в секундах")
    preferred_model: str = Field("grok", description="Предпочтительная модель (grok, antigravity и т.д.)")


# === Инициализация приложения ===
app = FastAPI(
    title="AgentForge Task Queue",
    description="Сервер очереди задач для оркестрации AI-агентов",
    version="1.0.0",
)

# CORS — разрешаем доступ из любого источника (дашборд, туннели, file://)
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Простая Bearer Token авторизация ===
# Токен из переменной окружения AGENTFORGE_API_KEY
# Если не задан — авторизация отключена (для обратной совместимости)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

AGENTFORGE_API_KEY = os.environ.get("AGENTFORGE_API_KEY", "")

class SimpleAuthMiddleware(BaseHTTPMiddleware):
    """Простая проверка Bearer токена. Пропускает /health и /dashboard."""
    async def dispatch(self, request, call_next):
        # Авторизация отключена если ключ не задан
        if not AGENTFORGE_API_KEY:
            return await call_next(request)
        # Пропускаем health и dashboard без авторизации
        path = request.url.path
        if path in ("/health", "/dashboard", "/docs", "/openapi.json") or path.startswith("/ws"):
            return await call_next(request)
        # Проверяем Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header == f"Bearer {AGENTFORGE_API_KEY}":
            return await call_next(request)
        # Также проверяем query param ?api_key= (для curl удобства)
        if request.query_params.get("api_key") == AGENTFORGE_API_KEY:
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized. Set Authorization: Bearer <key>"})

app.add_middleware(SimpleAuthMiddleware)
if AGENTFORGE_API_KEY:
    print(f"[AgentForge] 🔒 API auth ENABLED (key length: {len(AGENTFORGE_API_KEY)})")
else:
    print("[AgentForge] ⚠️ API auth DISABLED (set AGENTFORGE_API_KEY to enable)")


# === WebSocket: менеджер подключений для real-time логов ===

class ConnectionManager:
    """
    Менеджер WebSocket-подключений.
    Хранит активные подключения по task_id для стриминга обновлений.
    Поддерживает broadcast по всем подключениям (task_id='*').
    """
    def __init__(self):
        # Подключения по task_id: {task_id: [websocket, ...]}
        self.active_connections: dict[str, list[WebSocket]] = {}
        # Глобальные подключения (слушают все задачи)
        self.global_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, task_id: str = None):
        """Принять WebSocket-подключение и добавить в список"""
        await websocket.accept()
        if task_id and task_id != "*":
            if task_id not in self.active_connections:
                self.active_connections[task_id] = []
            self.active_connections[task_id].append(websocket)
        else:
            self.global_connections.append(websocket)
        total = self.count()
        print(f"[AgentForge WS] \U0001f50c Подключение: task_id={task_id or 'global'}, всего={total}")

    def disconnect(self, websocket: WebSocket, task_id: str = None):
        """Удалить WebSocket из активных подключений"""
        if task_id and task_id != "*" and task_id in self.active_connections:
            self.active_connections[task_id] = [
                ws for ws in self.active_connections[task_id] if ws != websocket
            ]
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
        else:
            self.global_connections = [ws for ws in self.global_connections if ws != websocket]
        total = self.count()
        print(f"[AgentForge WS] \U0001f534 Отключение: task_id={task_id or 'global'}, всего={total}")

    async def notify_task_update(self, task_id: str, data: dict):
        """
        Отправить обновление задачи всем подписчикам.
        Рассылает и по конкретному task_id, и глобальным слушателям.
        """
        message = json_module.dumps({
            "type": "task_update",
            "task_id": task_id,
            "data": data,
        }, ensure_ascii=False)
        
        # Отправляем подписчикам конкретной задачи
        stale = []
        for ws in self.active_connections.get(task_id, []):
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws, task_id)
        
        # Отправляем глобальным подписчикам
        stale_global = []
        for ws in self.global_connections:
            try:
                await ws.send_text(message)
            except Exception:
                stale_global.append(ws)
        for ws in stale_global:
            self.disconnect(ws)

    def count(self) -> int:
        """Общее число активных WebSocket-подключений"""
        total = len(self.global_connections)
        for conns in self.active_connections.values():
            total += len(conns)
        return total


# Глобальный экземпляр менеджера подключений
ws_manager = ConnectionManager()

# === Работа с базой данных ===

async def get_db() -> aiosqlite.Connection:
    """Получить подключение к БД (с поддержкой Row-доступа по именам)"""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

async def init_db():
    """Инициализация таблицы задач в SQLite"""
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                priority TEXT DEFAULT 'medium',
                complexity TEXT DEFAULT 'medium',
                preferred_agent TEXT DEFAULT 'auto',
                status TEXT DEFAULT 'pending',
                assigned_agent TEXT,
                result TEXT,
                git_branch TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                tags TEXT DEFAULT '[]'
            )
        """)
        await db.commit()
        
        # Миграция: добавляем поля для трекинга затрат + skill (playbook)
        for col in [
            "ALTER TABLE tasks ADD COLUMN duration_seconds REAL",
            "ALTER TABLE tasks ADD COLUMN started_at TEXT",
            "ALTER TABLE tasks ADD COLUMN completed_at TEXT",
            "ALTER TABLE tasks ADD COLUMN skill TEXT",
            "ALTER TABLE tasks ADD COLUMN retry_count INTEGER DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN tokens_used INTEGER DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN cost_usd REAL DEFAULT 0.0",
        ]:
            try:
                await db.execute(col)
            except Exception:
                pass  # Колонка уже существует
        await db.commit()

        # Таблица чекпоинтов для промежуточного состояния задач
        await db.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT '{}',
                step_index INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)

        # Таблица зарегистрированных вебхуков для уведомлений
        await db.execute("""
            CREATE TABLE IF NOT EXISTS webhooks (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                events TEXT NOT NULL DEFAULT '["status_change"]',
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()
    finally:
        await db.close()

# === Логика маршрутизации агентов ===
# Изменено в рамках рефакторинга 2026-06 (Фаза 1)
# См. AGENTFORGE_ROUTING_AND_EXECUTION_REFACTOR_PLAN.md
# Основная идея: Grok — дефолт, Antigravity только по явному запросу или специальным тегам.

def resolve_agent(task: dict) -> str:
    """
    Автоматическая маршрутизация задачи к подходящему агенту.

    Новая философия (см. AGENTFORGE_ROUTING_AND_EXECUTION_REFACTOR_PLAN.md):

    - Grok — основной исполнитель по умолчанию (самый зрелый раннер).
    - Jules — только при явных сигналах, что нужна работа с PR / документацией / тестами.
    - Antigravity — только при ЯВНОМ желании пользователя (explicit preferred_agent=antigravity)
      или при очень специфических тегах глубокого архитектурного анализа.
      В большинстве случаев сложные задачи теперь идут на Grok.

    Это исправляет ситуацию, когда почти все интересные задачи автоматически
    улетали на Antigravity, у которого нет нормального автоматического исполнения.
    """
    preferred = str(task.get("preferred_agent", "auto")).lower()

    # Правило 1: явно указанный агент уважаем (кроме legacy "agy")
    if preferred in ("grok", "jules", "antigravity"):
        return preferred
    if preferred == "agy":
        return "antigravity"

    # Если явно auto или неизвестно — анализируем дальше
    tags = task.get("tags", [])
    if isinstance(tags, str):
        import json
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    tags_lower = [t.lower() for t in tags]

    # Сильные сигналы для Jules (PR / Docs / Tests heavy)
    jules_signals = ["pr", "pull-request", "github", "documentation", "docs-heavy",
                     "tests-heavy", "test-heavy", "refactor-with-tests"]
    if any(sig in tags_lower for sig in jules_signals):
        return "jules"

    # Очень узкие сигналы для Antigravity (только глубокий архитектурный разбор)
    antigravity_signals = [
        "deep-analysis", "architecture-decision", "critical-review",
        "antigravity", "antigravity-only", "principal-architect"
    ]
    if any(sig in tags_lower for sig in antigravity_signals):
        return "antigravity"

    # Всё остальное — Grok (включая большинство complex задач, rust, краулеры,
    # интеграции, оптимизации, server-side работу и т.д.)
    return "grok"


# === Skills / Playbooks: YAML-шаблоны (подбор по тегам) ===

def load_skills() -> dict:
    """Загрузка всех YAML playbooks из ~/agentforge/skills/"""
    skills: dict = {}
    if not os.path.isdir(SKILLS_DIR):
        return skills
    for fname in sorted(os.listdir(SKILLS_DIR)):
        if not fname.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(SKILLS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            skill_name = data.get("name") or fname.rsplit(".", 1)[0]
            skills[skill_name] = data
            # Также доступно по имени файла без расширения
            base = fname.rsplit(".", 1)[0]
            if base not in skills:
                skills[base] = data
        except Exception as e:
            print(f"[AgentForge Skills] ⚠️ Не удалось загрузить {fname}: {e}")
    return skills


_skills_cache: Optional[dict] = None


def get_skills() -> dict:
    """Кэшированный доступ к skills"""
    global _skills_cache
    if _skills_cache is None:
        _skills_cache = load_skills()
    return _skills_cache


def save_skill_to_disk(skill_data: dict) -> str:
    """
    Self-Expansion core: сохраняет новый YAML-playbook в ~/agentforge/skills/.
    Инвалидирует кэш, чтобы select_skill сразу видел новый skill.
    Используется как из API, так и из skill_capture.py.
    Возвращает путь к файлу.
    """
    os.makedirs(SKILLS_DIR, exist_ok=True)
    name = skill_data.get("name") or "unnamed-skill"
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(name).lower())
    safe = "-".join(filter(None, safe.split("-")))[:64] or "unnamed-skill"

    path = os.path.join(SKILLS_DIR, f"{safe}.yaml")

    header = (
        "# =============================================================================\n"
        f"# AgentForge Skill: {safe}\n"
        "# =============================================================================\n"
        "# Автоматически сгенерирован через Tool Creation / self-expansion.\n"
        "# Другие агенты получат system_prompt при совпадении required_tags.\n"
        "# =============================================================================\n\n"
    )

    # Только разрешённые поля
    allowed = ("name", "description", "system_prompt", "required_tags", "ci_checks", "timeout", "preferred_model")
    clean: dict = {k: skill_data.get(k) for k in allowed if k in skill_data}

    body = yaml.safe_dump(clean, allow_unicode=True, sort_keys=False, width=100, default_flow_style=False)

    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body)

    global _skills_cache
    _skills_cache = None  # force reload on next get_skills()

    print(f"[AgentForge Skills] ✅ Self-expansion: captured new skill '{safe}' → {path}")
    return path


def capture_skill_from_dict(data: dict) -> dict:
    """Удобный wrapper для вызова из раннеров и агентов."""
    path = save_skill_to_disk(data)
    return {
        "status": "captured",
        "name": data.get("name"),
        "path": path,
    }


def select_skill(task: dict) -> Optional[str]:
    """
    При dispatch: подбор skill по пересечению тегов задачи и required_tags в YAML.
    Возвращает имя skill (из поля name или basename файла) или None.
    Приоритет: явное указание в таске > авто-подбор.
    """
    # Явный оверрайд
    explicit = task.get("skill") or task.get("selected_skill")
    if explicit:
        return explicit

    skills = get_skills()
    if not skills:
        return None

    tags = task.get("tags", [])
    if isinstance(tags, str):
        try:
            tags = json_module.loads(tags)
        except Exception:
            tags = []
    tags_lower = {str(t).lower() for t in tags if t}

    if not tags_lower:
        return None

    for sname, sdata in skills.items():
        if sname.endswith(".yaml") or sname.endswith(".yml"):
            continue
        req = sdata.get("required_tags", []) or []
        req_lower = {str(r).lower() for r in req if r}
        overlap = tags_lower & req_lower
        if overlap:
            # Логируем почему выбран (полезно при отладке self-expansion)
            print(f"[AgentForge Skills] select_skill: '{sdata.get('name') or sname}' matched via {overlap}")
            return sdata.get("name") or sname
    return None


# === Вспомогательные функции ===

def row_to_dict(row) -> dict:
    """Преобразование строки SQLite в словарь"""
    import json
    d = dict(row)
    # Парсим tags из JSON-строки обратно в список
    if "tags" in d and isinstance(d["tags"], str):
        try:
            d["tags"] = json.loads(d["tags"])
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
    # skill может быть NULL -> None
    if d.get("skill") in ("", None):
        d["skill"] = None
    return d

def now_iso() -> str:
    """Текущее время в ISO формате (UTC)"""
    return datetime.now(timezone.utc).isoformat()

# === События жизненного цикла приложения ===

@app.on_event("startup")
async def startup():
    """Инициализация БД при старте сервера"""
    # Создаём директорию для БД если не существует
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    await init_db()
    print("[AgentForge] ✅ Сервер очереди задач запущен")
    print(f"[AgentForge] 📂 БД: {DB_PATH}")

# === Эндпоинты API ===

@app.get("/health", tags=["Система"])
async def health_check():
    """Проверка здоровья сервера"""
    return {
        "status": "ok",
        "service": "AgentForge Task Queue",
        "version": "1.0.0",
        "timestamp": now_iso(),
    }

@app.get('/dashboard', response_class=HTMLResponse, tags=['Дашборд'])
async def dashboard():
    """Веб-дашборд для мониторинга задач AgentForge"""
    dashboard_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.html')
    if os.path.exists(dashboard_path):
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content='<h1>Dashboard not found</h1>', status_code=404)

@app.post("/tasks", response_model=TaskResponse, status_code=201, tags=["Задачи"])
async def create_task(task: TaskCreate):
    """
    Создание новой задачи в очереди.
    
    Генерирует уникальный UUID, устанавливает начальный статус 'pending',
    и создаёт имя git-ветки для задачи.
    """
    import json
    
    task_id = str(uuid.uuid4())[:8]  # Короткий UUID для удобства
    now = now_iso()
    git_branch = f"agentforge/{task_id}"
    
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO tasks (id, title, description, priority, complexity, 
                             preferred_agent, status, git_branch, created_at, updated_at, tags, skill)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                task.title,
                task.description,
                task.priority.value,
                task.complexity.value,
                task.preferred_agent.value,
                TaskStatus.pending.value,
                git_branch,
                now,
                now,
                json.dumps(task.tags, ensure_ascii=False),
                task.skill,
            ),
        )
        await db.commit()
        
        # Получаем созданную задачу для ответа
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        
        print(f"[AgentForge] 📋 Создана задача: {task_id} — {task.title}")
        
        # WebSocket: уведомляем о новой задаче
        new_task = row_to_dict(row)
        await ws_manager.notify_task_update(task_id, new_task)
        
        # Webhooks: уведомляем о создании новой задачи
        await _notify_webhooks("task_created", new_task)
        
        return new_task
    finally:
        await db.close()

@app.get("/tasks", response_model=list[TaskResponse], tags=["Задачи"])
async def list_tasks(status: Optional[TaskStatus] = None):
    """
    Получение списка всех задач.
    
    Опциональная фильтрация по статусу через query-параметр ?status=pending
    """
    db = await get_db()
    try:
        if status:
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                (status.value,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            )
        rows = await cursor.fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        await db.close()

@app.get("/tasks/{task_id}", response_model=TaskResponse, tags=["Задачи"])
async def get_task(task_id: str):
    """Получение задачи по ID"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        return row_to_dict(row)
    finally:
        await db.close()

@app.patch("/tasks/{task_id}", response_model=TaskResponse, tags=["Задачи"])
async def update_task(task_id: str, update: TaskUpdate):
    """
    Обновление задачи — статус, результат, назначенный агент.
    
    Используется агентами для отчёта о прогрессе и результатах.
    """
    db = await get_db()
    try:
        # Проверяем существование задачи
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        # Собираем поля для обновления
        updates = []
        values = []
        
        if update.status is not None:
            updates.append("status = ?")
            values.append(update.status.value)
            
            # Авто-установка started_at при переходе в in_progress/dispatched
            if update.status.value in ("in_progress", "dispatched"):
                updates.append("started_at = ?")
                values.append(now_iso())
            
            # Авто-установка completed_at при переходе в done/review
            if update.status.value in ("done", "review"):
                updates.append("completed_at = ?")
                values.append(now_iso())
        
        if update.result is not None:
            updates.append("result = ?")
            values.append(update.result)
        
        if update.assigned_agent is not None:
            updates.append("assigned_agent = ?")
            values.append(update.assigned_agent)
        
        if update.duration_seconds is not None:
            updates.append("duration_seconds = ?")
            values.append(update.duration_seconds)
        

        if update.skill is not None:
            updates.append("skill = ?")
            values.append(update.skill)
            
        if update.retry_count is not None:
            updates.append("retry_count = ?")
            values.append(update.retry_count)
            
        if update.tokens_used is not None:
            updates.append("tokens_used = ?")
            values.append(update.tokens_used)
            
        if update.cost_usd is not None:
            updates.append("cost_usd = ?")
            values.append(update.cost_usd)

        
        if not updates:
            raise HTTPException(status_code=400, detail="Нет полей для обновления")
        
        # Обновляем updated_at
        updates.append("updated_at = ?")
        values.append(now_iso())
        values.append(task_id)
        
        query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
        await db.execute(query, values)
        await db.commit()
        
        # Возвращаем обновлённую задачу
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        
        print(f"[AgentForge] 🔄 Обновлена задача: {task_id}")
        
        # WebSocket: отправляем real-time уведомление подписчикам
        updated_task = row_to_dict(row)
        await ws_manager.notify_task_update(task_id, updated_task)
        
        # Webhooks: уведомляем зарегистрированные вебхуки при смене статуса
        if update.status is not None:
            await _notify_webhooks("status_change", updated_task)
            # Дополнительное событие при завершении задачи
            if update.status.value in ("done", "failed"):
                await _notify_webhooks("task_completed", updated_task)
        
        return updated_task
    finally:
        await db.close()

# === Эндпоинты State Checkpoints ===

@app.post("/tasks/{task_id}/checkpoint", tags=["Чекпоинты"], status_code=201)
async def create_checkpoint(task_id: str, checkpoint: CheckpointCreate):
    """
    Сохранить промежуточное состояние (чекпоинт) задачи.
    
    Позволяет агенту сохранять прогресс выполнения задачи,
    чтобы в случае сбоя можно было продолжить с последнего чекпоинта.
    """
    import json
    
    db = await get_db()
    try:
        # Проверяем что задача существует
        cursor = await db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        checkpoint_id = str(uuid.uuid4())[:8]
        now = now_iso()
        
        await db.execute(
            """
            INSERT INTO checkpoints (id, task_id, state, step_index, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint_id,
                task_id,
                json.dumps(checkpoint.state, ensure_ascii=False),
                checkpoint.step_index,
                checkpoint.message,
                now,
            ),
        )
        await db.commit()
        
        print(f"[AgentForge] 💾 Чекпоинт {checkpoint_id} сохранён для задачи {task_id} (шаг {checkpoint.step_index})")
        
        return {
            "id": checkpoint_id,
            "task_id": task_id,
            "state": checkpoint.state,
            "step_index": checkpoint.step_index,
            "message": checkpoint.message,
            "created_at": now,
        }
    finally:
        await db.close()


@app.get("/tasks/{task_id}/checkpoint", tags=["Чекпоинты"])
async def get_latest_checkpoint(task_id: str):
    """
    Получить последний чекпоинт задачи.
    
    Возвращает самое свежее промежуточное состояние,
    с которого агент может продолжить выполнение.
    """
    import json
    
    db = await get_db()
    try:
        # Проверяем что задача существует
        cursor = await db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        # Получаем последний чекпоинт
        cursor = await db.execute(
            "SELECT * FROM checkpoints WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        )
        checkpoint = await cursor.fetchone()
        
        if not checkpoint:
            return {
                "task_id": task_id,
                "checkpoint": None,
                "message": "Чекпоинтов для этой задачи пока нет",
            }
        
        return {
            "id": checkpoint[0],
            "task_id": checkpoint[1],
            "state": json.loads(checkpoint[2]) if checkpoint[2] else {},
            "step_index": checkpoint[3],
            "message": checkpoint[4],
            "created_at": checkpoint[5],
        }
    finally:
        await db.close()


@app.get("/tasks/{task_id}/checkpoints", tags=["Чекпоинты"])
async def get_all_checkpoints(task_id: str):
    """
    Получить все чекпоинты задачи (история промежуточных состояний).
    
    Возвращает список всех сохранённых чекпоинтов в хронологическом порядке.
    """
    import json
    
    db = await get_db()
    try:
        # Проверяем что задача существует
        cursor = await db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        cursor = await db.execute(
            "SELECT * FROM checkpoints WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        )
        rows = await cursor.fetchall()
        
        checkpoints = []
        for cp in rows:
            checkpoints.append({
                "id": cp[0],
                "task_id": cp[1],
                "state": json.loads(cp[2]) if cp[2] else {},
                "step_index": cp[3],
                "message": cp[4],
                "created_at": cp[5],
            })
        
        return {
            "task_id": task_id,
            "total": len(checkpoints),
            "checkpoints": checkpoints,
        }
    finally:
        await db.close()


# === Эндпоинты Notification Webhooks ===

async def _notify_webhooks(event_type: str, task_data: dict):
    """
    Внутренняя функция: отправить уведомление на все активные вебхуки.
    Вызывается при смене статуса задачи или других событиях.
    """
    import json
    import aiohttp
    
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT url, events FROM webhooks WHERE active = 1"
        )
        hooks = await cursor.fetchall()
    finally:
        await db.close()
    
    for hook in hooks:
        hook_url = hook[0]
        hook_events = json.loads(hook[1]) if hook[1] else []
        
        # Проверяем что вебхук подписан на этот тип события
        if event_type not in hook_events and "*" not in hook_events:
            continue
        
        # Отправляем POST-запрос на URL вебхука (fire-and-forget)
        payload = {
            "event": event_type,
            "timestamp": now_iso(),
            "data": task_data,
        }
        
        try:
            # Используем asyncio.create_task чтобы не блокировать основной поток
            async def _send(url, data):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url,
                            json=data,
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            print(f"[AgentForge Webhook] 📤 {url} → {resp.status}")
                except Exception as e:
                    print(f"[AgentForge Webhook] ⚠️ Ошибка отправки на {url}: {e}")
            
            asyncio.create_task(_send(hook_url, payload))
        except Exception as e:
            print(f"[AgentForge Webhook] ⚠️ Не удалось создать задачу для {hook_url}: {e}")


@app.post("/webhooks/register", tags=["Вебхуки"], status_code=201)
async def register_webhook(webhook: WebhookRegister):
    """
    Зарегистрировать вебхук для получения уведомлений.
    
    При смене статуса задачи или других событиях сервер отправит
    POST-запрос на указанный URL с данными о событии.
    
    Поддерживаемые типы событий:
    - status_change: при любом изменении статуса задачи
    - task_created: при создании новой задачи
    - task_completed: при переходе задачи в done/failed
    """
    import json
    
    webhook_id = str(uuid.uuid4())[:8]
    now = now_iso()
    
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO webhooks (id, url, events, active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                webhook_id,
                webhook.url,
                json.dumps(webhook.events, ensure_ascii=False),
                now,
            ),
        )
        await db.commit()
        
        print(f"[AgentForge] 🔔 Вебхук {webhook_id} зарегистрирован: {webhook.url} → {webhook.events}")
        
        return {
            "id": webhook_id,
            "url": webhook.url,
            "events": webhook.events,
            "active": True,
            "created_at": now,
        }
    finally:
        await db.close()


@app.get("/webhooks", tags=["Вебхуки"])
async def list_webhooks():
    """Получить список всех зарегистрированных вебхуков"""
    import json
    
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM webhooks ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        
        webhooks = []
        for row in rows:
            webhooks.append({
                "id": row[0],
                "url": row[1],
                "events": json.loads(row[2]) if row[2] else [],
                "active": bool(row[3]),
                "created_at": row[4],
            })
        
        return {"total": len(webhooks), "webhooks": webhooks}
    finally:
        await db.close()


@app.delete("/webhooks/{webhook_id}", tags=["Вебхуки"])
async def delete_webhook(webhook_id: str):
    """Удалить (деактивировать) вебхук"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM webhooks WHERE id = ?", (webhook_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Вебхук {webhook_id} не найден")
        
        await db.execute("UPDATE webhooks SET active = 0 WHERE id = ?", (webhook_id,))
        await db.commit()
        
        print(f"[AgentForge] 🔕 Вебхук {webhook_id} деактивирован")
        return {"id": webhook_id, "active": False, "message": "Вебхук деактивирован"}
    finally:
        await db.close()


@app.post("/tasks/{task_id}/dispatch", tags=["Диспетчеризация"])
async def dispatch_task(task_id: str):
    """
    Диспетчеризация задачи — определяет подходящего агента и запускает выполнение.
    
    Использует автоматическую маршрутизацию + подбор YAML skill/playbook по тегам.
    При совпадении required_tags → system_prompt из skill добавляется в промпт агента.
    """
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        task = row_to_dict(row)
        
        # Проверяем, что задача ещё не была отправлена
        if task["status"] not in ("pending", "failed"):
            raise HTTPException(
                status_code=409,
                detail=f"Задача {task_id} уже имеет статус '{task['status']}', "
                       f"диспетчеризация доступна только для pending/failed"
            )
        
        # Определяем агента через маршрутизацию
        agent = resolve_agent(task)
        
        # === НОВОЕ: подбор skill/playbook по тегам задачи ===
        skill = select_skill(task)
        if skill:
            print(f"[AgentForge Skills] Подобран skill '{skill}' для задачи {task_id} по тегам")
        
        # Важное предупреждение при маршрутизации на Antigravity
        if agent == "antigravity":
            print(f"[AgentForge WARNING] ⚠️  Задача {task_id} направлена на Antigravity. "
                  "Это human-in-the-loop режим. Задача не будет выполнена автоматически. "
                  "См. AGENTFORGE_ROUTING_AND_EXECUTION_REFACTOR_PLAN.md")
        
        # Обновляем статус, агента и skill
        now = now_iso()
        await db.execute(
            "UPDATE tasks SET status = ?, assigned_agent = ?, skill = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.dispatched.value, agent, skill, now, task_id),
        )
        await db.commit()
        
        # Запускаем dispatcher.sh в фоновом режиме (5-й аргумент = skill)
        if os.path.exists(DISPATCHER_PATH):
            skill_arg = skill or ""
            subprocess.Popen(
                ["bash", DISPATCHER_PATH, task_id, agent, task["description"], task["priority"], skill_arg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[AgentForge] 🚀 Задача {task_id} отправлена агенту: {agent} (skill={skill or 'none'})")
        else:
            print(f"[AgentForge] ⚠️ Dispatcher не найден: {DISPATCHER_PATH}")
            print(f"[AgentForge] 📌 Задача {task_id} назначена агенту: {agent} (ручной запуск)")
        
        # WebSocket: уведомляем о диспетчеризации задачи
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if row:
            await ws_manager.notify_task_update(task_id, row_to_dict(row))
        
        return {
            "task_id": task_id,
            "assigned_agent": agent,
            "skill": skill,
            "status": "dispatched",
            "message": f"Задача отправлена агенту '{agent}' (skill={skill or 'default'})",
        }
    finally:
        await db.close()


# === Self-Expansion: Tool Creation API (автогенерация YAML skills) ===

@app.post("/skills/capture", tags=["Skills / Self-Expansion"])
async def capture_skill_endpoint(skill: SkillCapture):
    """
    Главная точка входа для self-expansion.
    Агент, написавший новый скрипт/парсер/API-клиент/деплой-тул, вызывает этот эндпоинт
    (или использует /home/agx/agentforge/skill_capture.py), чтобы сохранить YAML-playbook.
    После этого другие агенты с подходящими тегами будут автоматически получать system_prompt.
    """
    data = skill.dict()
    path = save_skill_to_disk(data)
    return {
        "status": "captured",
        "name": data["name"],
        "path": path,
        "required_tags": data.get("required_tags", []),
        "message": "Skill saved to ~/agentforge/skills/. Future tasks with overlapping tags will auto-select it.",
    }


@app.get("/skills", tags=["Skills / Self-Expansion"])
async def list_skills():
    """Список всех загруженных playbooks (для отладки и для агентов)."""
    skills = get_skills()
    # Убираем дубли по basename
    clean = {}
    for k, v in skills.items():
        if k.endswith((".yaml", ".yml")):
            continue
        clean[k] = {
            "name": v.get("name", k),
            "description": v.get("description", ""),
            "required_tags": v.get("required_tags", []),
            "timeout": v.get("timeout"),
        }
    return {"count": len(clean), "skills": clean, "skills_dir": SKILLS_DIR}


# === Эндпоинт метрик ===

@app.get('/metrics', tags=['Метрики'])
async def get_metrics():
    """Метрики системы AgentForge"""
    db = await get_db()
    try:
        # Общее количество задач
        cursor = await db.execute("SELECT COUNT(*) as total FROM tasks")
        total = (await cursor.fetchone())[0]
        
        # По статусам
        cursor = await db.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status")
        by_status = {row[0]: row[1] for row in await cursor.fetchall()}
        
        # По агентам
        cursor = await db.execute("SELECT assigned_agent, COUNT(*) as cnt FROM tasks WHERE assigned_agent IS NOT NULL GROUP BY assigned_agent")
        by_agent = {row[0]: row[1] for row in await cursor.fetchall()}
        
        # По приоритетам
        cursor = await db.execute("SELECT priority, COUNT(*) as cnt FROM tasks GROUP BY priority")
        by_priority = {row[0]: row[1] for row in await cursor.fetchall()}
        
        # Среднее время выполнения (для завершённых задач)
        cursor = await db.execute("""
            SELECT AVG(
                (julianday(updated_at) - julianday(created_at)) * 86400
            ) as avg_seconds
            FROM tasks WHERE status IN ('done', 'review')
        """)
        avg_row = await cursor.fetchone()
        avg_completion_seconds = round(avg_row[0], 1) if avg_row[0] else None
        
        # Среднее время по агентам (performance tracking)
        cursor = await db.execute("""
            SELECT assigned_agent, 
                   AVG(duration_seconds) as avg_duration,
                   COUNT(*) as completed
            FROM tasks 
            WHERE duration_seconds IS NOT NULL AND assigned_agent IS NOT NULL
            GROUP BY assigned_agent
        """)
        agent_performance = {row[0]: {"avg_seconds": round(row[1], 1), "completed": row[2]} for row in await cursor.fetchall()}
        
        return {
            "total_tasks": total,
            "by_status": by_status,
            "by_agent": by_agent,
            "by_priority": by_priority,
            "avg_completion_seconds": avg_completion_seconds,
            "agent_performance": agent_performance,
            "timestamp": now_iso(),
        }
    finally:
        await db.close()

@app.get('/agents', tags=['Агенты'])
async def get_agents():
    """Список агентов и их Agent Cards"""
    cards_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_cards.json')
    if os.path.exists(cards_path):
        import json
        with open(cards_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"agents": [], "error": "agent_cards.json not found"}


@app.get("/skills", tags=["Skills/Playbooks"])
async def list_skills():
    """Список доступных YAML playbooks (skills). system_prompt обрезан для краткости."""
    skills = get_skills()
    out = []
    for name, data in skills.items():
        if name.endswith(".yaml") or name.endswith(".yml"):
            continue
        out.append({
            "name": name,
            "description": (data.get("description") or "")[:200],
            "required_tags": data.get("required_tags", []),
            "timeout": data.get("timeout", 900),
            "preferred_model": data.get("preferred_model", "grok"),
            "has_system_prompt": bool(data.get("system_prompt")),
            "ci_checks_count": len(data.get("ci_checks", [])),
        })
    return {"skills": out, "count": len(out), "dir": SKILLS_DIR}


# === Guardian Agent (Автоматический код-ревью) ===


# === Arena Mode: запуск задачи у двух агентов и выбор лучшего результата ===

class ArenaRequest(BaseModel):
    """Модель запроса Arena Mode"""
    agent_a: str = Field("grok", description="Первый агент для соревнования")
    agent_b: str = Field("jules", description="Второй агент для соревнования")


class MoARequest(BaseModel):
    """Модель запроса Mixture-of-Agents (MoA)"""
    num_proposals: int = Field(3, ge=2, le=5, description="Количество параллельных proposer-агентов (2-5)")
    aggregator: str = Field("grok", description="Агент-агрегатор, синтезирующий финальный результат из всех предложений")

@app.post('/tasks/{task_id}/arena', tags=['Arena'])
async def arena_mode(task_id: str, arena: ArenaRequest = ArenaRequest()):
    """
    Arena Mode — запускает задачу у двух агентов параллельно.
    
    Создаёт две копии задачи (суффиксы -arena-a и -arena-b),
    запускает обоих агентов, и после завершения Guardian выбирает лучший результат.
    Оригинальная задача получает результат победителя.
    """
    db = await get_db()
    try:
        # Получаем оригинальную задачу
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        task = row_to_dict(row)
        
        # Проверяем что задача в pending
        if task["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Arena доступна только для pending задач (текущий: {task['status']})"
            )
        
        now = now_iso()
        arena_tasks = []
        
        # Создаём две копии задачи для каждого агента
        for suffix, agent in [("arena-a", arena.agent_a), ("arena-b", arena.agent_b)]:
            arena_id = f"{task_id[:8]}-{suffix}"
            tags = task.get("tags", [])
            if isinstance(tags, str):
                import json as _json
                try:
                    tags = _json.loads(tags)
                except Exception:
                    tags = []
            tags_with_arena = tags + ["arena", f"arena-{task_id[:8]}"]
            
            await db.execute(
                """INSERT OR REPLACE INTO tasks 
                   (id, title, description, priority, complexity, preferred_agent,
                    status, assigned_agent, result, git_branch, created_at, updated_at, tags, skill)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    arena_id,
                    f"[Arena {suffix[-1].upper()}] {task['title']}",
                    task["description"],
                    task["priority"],
                    task["complexity"],
                    agent,
                    "pending",
                    None,
                    None,
                    f"agentforge/{arena_id}",
                    now,
                    now,
                    json_module.dumps(tags_with_arena, ensure_ascii=False),
                    task.get("skill"),
                )
            )
            arena_tasks.append({"id": arena_id, "agent": agent})
        
        # Помечаем оригинальную задачу как arena
        await db.execute(
            "UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE id = ?",
            ("in_progress", f"Arena: {arena.agent_a} vs {arena.agent_b}", now, task_id)
        )
        await db.commit()
        
        # Диспатчим обе задачи
        for at in arena_tasks:
            try:
                subprocess.Popen(
                    ["bash", DISPATCHER_PATH, at["id"]],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                print(f"[AgentForge Arena] Не удалось диспатчить {at['id']}: {e}")
        
        # Уведомляем WebSocket
        await ws_manager.notify_task_update(task_id, {
            "status": "in_progress",
            "result": f"Arena: {arena.agent_a} vs {arena.agent_b}",
            "arena_tasks": arena_tasks,
        })
        
        print(f"[AgentForge Arena] Запущен Arena Mode для {task_id}: {arena.agent_a} vs {arena.agent_b}")
        
        return {
            "task_id": task_id,
            "mode": "arena",
            "agent_a": {"id": arena_tasks[0]["id"], "agent": arena.agent_a},
            "agent_b": {"id": arena_tasks[1]["id"], "agent": arena.agent_b},
            "message": f"Arena Mode запущен: {arena.agent_a} vs {arena.agent_b}",
        }
    finally:
        await db.close()


@app.post('/tasks/{task_id}/arena/judge', tags=['Arena'])
async def arena_judge(task_id: str):
    """
    Судья Arena — сравнивает результаты двух агентов и выбирает победителя.
    
    Критерии оценки:
    - done статус лучше чем review, review лучше чем failed
    - Guardian approved даёт бонус
    - Меньшее время выполнения даёт бонус
    Результат победителя применяется к оригинальной задаче.
    """
    db = await get_db()
    try:
        # Находим arena-подзадачи
        arena_a_id = f"{task_id[:8]}-arena-a"
        arena_b_id = f"{task_id[:8]}-arena-b"
        
        cursor_a = await db.execute("SELECT * FROM tasks WHERE id = ?", (arena_a_id,))
        cursor_b = await db.execute("SELECT * FROM tasks WHERE id = ?", (arena_b_id,))
        row_a = await cursor_a.fetchone()
        row_b = await cursor_b.fetchone()
        
        if not row_a or not row_b:
            raise HTTPException(status_code=404, detail="Arena подзадачи не найдены")
        
        task_a = row_to_dict(row_a)
        task_b = row_to_dict(row_b)
        
        # Скоринг
        def score_task(t):
            """Подсчёт очков для задачи в Arena"""
            s = 0
            status = t.get("status", "")
            result = t.get("result", "") or ""
            # Статус: done > review > остальные
            if status == "done":
                s += 10
            elif status == "review":
                s += 5
            elif status == "failed":
                s -= 10
            # Guardian approved
            if "approved" in result.lower():
                s += 5
            # Время выполнения (меньше = лучше)
            duration = t.get("duration_seconds") or 9999
            if isinstance(duration, (int, float)):
                if duration < 60:
                    s += 3
                elif duration < 180:
                    s += 1
            return s
        
        score_a = score_task(task_a)
        score_b = score_task(task_b)
        
        # Определяем победителя
        if score_a >= score_b:
            winner = task_a
            winner_label = "A"
        else:
            winner = task_b
            winner_label = "B"
        
        now = now_iso()
        verdict = (
            f"Arena: Победитель — агент {winner_label} ({winner.get('assigned_agent', '?')}) "
            f"[A={score_a}, B={score_b}]"
        )
        
        # Обновляем оригинальную задачу результатом победителя
        await db.execute(
            "UPDATE tasks SET status = ?, result = ?, assigned_agent = ?, updated_at = ? WHERE id = ?",
            ("done", verdict, winner.get("assigned_agent"), now, task_id)
        )
        await db.commit()
        
        # Уведомляем WebSocket
        await ws_manager.notify_task_update(task_id, {
            "status": "done",
            "result": verdict,
        })
        
        print(f"[AgentForge Arena] {task_id}: победитель — {winner_label} ({winner.get('assigned_agent')})")
        
        return {
            "task_id": task_id,
            "winner": winner_label,
            "winner_agent": winner.get("assigned_agent"),
            "score_a": score_a,
            "score_b": score_b,
            "verdict": verdict,
        }
    finally:
        await db.close()


# === Mixture-of-Agents (MoA): N parallel proposers + 1 aggregator (DeepMind pattern) ===

@app.post('/tasks/{task_id}/moa', tags=['MoA'])
async def moa_mode(task_id: str, moa: MoARequest = MoARequest()):
    """
    Mixture-of-Agents (MoA) — расширенная Arena Mode.
    
    Паттерн DeepMind: несколько proposer-агентов генерируют параллельные решения,
    затем aggregator-агент синтезирует лучший результат.
    
    Создаёт N подзадач-предложений (суффиксы -moa-p1, -moa-p2, ...),
    диспатчит их параллельно (через /dispatch для корректного выбора агента).
    Оригинальная задача переводится в in_progress.
    После завершения всех предложений используйте /moa/aggregate для запуска агрегатора.
    """
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        task = row_to_dict(row)
        
        if task["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"MoA доступна только для pending задач (текущий: {task['status']})"
            )
        
        n = max(2, min(5, moa.num_proposals))
        now = now_iso()
        proposal_tasks = []
        
        # Выбираем разнообразных proposers (цикл по сильным агентам)
        proposer_pool = ["grok", "antigravity", "grok", "jules", "grok"]
        
        for i in range(1, n + 1):
            proposal_id = f"{task_id[:8]}-moa-p{i}"
            proposer = proposer_pool[(i - 1) % len(proposer_pool)]
            
            tags = task.get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json_module.loads(tags)
                except Exception:
                    tags = []
            tags_with_moa = tags + ["moa", f"moa-{task_id[:8]}", "proposer"]
            
            await db.execute(
                """INSERT OR REPLACE INTO tasks 
                   (id, title, description, priority, complexity, preferred_agent,
                    status, assigned_agent, result, git_branch, created_at, updated_at, tags, skill)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal_id,
                    f"[MoA Proposal {i}/{n}] {task['title']}",
                    task["description"],
                    task["priority"],
                    task["complexity"],
                    proposer,
                    "pending",
                    None,
                    None,
                    f"agentforge/{proposal_id}",
                    now,
                    now,
                    json_module.dumps(tags_with_moa, ensure_ascii=False),
                    task.get("skill"),
                )
            )
            proposal_tasks.append({"id": proposal_id, "agent": proposer})
        
        # Обновляем оригинальную задачу
        await db.execute(
            "UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE id = ?",
            ("in_progress", f"MoA: {n} proposals (aggregator={moa.aggregator})", now, task_id)
        )
        await db.commit()
        
        # Диспатчим все proposal-задачи через API (корректно устанавливает assigned_agent + запускает runner)
        for p in proposal_tasks:
            try:
                subprocess.Popen(
                    ["curl", "-s", "-X", "POST", f"http://127.0.0.1:8080/tasks/{p['id']}/dispatch",
                     "-o", "/dev/null"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                print(f"[AgentForge MoA] Не удалось диспатчить {p['id']}: {e}")
        
        await ws_manager.notify_task_update(task_id, {
            "status": "in_progress",
            "result": f"MoA: {n} proposals (aggregator={moa.aggregator})",
            "moa_proposals": proposal_tasks,
        })
        
        print(f"[AgentForge MoA] Запущен MoA для {task_id}: {n} proposers + aggregator={moa.aggregator}")
        
        return {
            "task_id": task_id,
            "mode": "moa",
            "num_proposals": n,
            "proposals": proposal_tasks,
            "aggregator": moa.aggregator,
            "message": f"MoA запущен: {n} параллельных предложений. Используйте POST /tasks/{task_id}/moa/aggregate для синтеза.",
        }
    finally:
        await db.close()


@app.post('/tasks/{task_id}/moa/aggregate', tags=['MoA'])
async def moa_aggregate(task_id: str, aggregator: Optional[str] = None):
    """
    Запуск aggregator-агента для MoA.
    
    Собирает результаты всех proposal-подзадач (moa-p*), формирует
    детальный промпт с инструкцией синтеза (паттерн DeepMind MoA),
    создаёт отдельную aggregator-задачу {id}-moa-agg и диспатчит её.
    После завершения агрегатора используйте /moa/finalize для применения результата.
    """
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        orig_task = row_to_dict(row)
        
        # Находим все proposal subtasks
        prefix = f"{task_id[:8]}-moa-p"
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE id LIKE ? ORDER BY id",
            (prefix + "%",)
        )
        proposal_rows = await cursor.fetchall()
        
        if not proposal_rows:
            raise HTTPException(status_code=404, detail="MoA proposal-подзадачи не найдены. Сначала вызовите /moa")
        
        proposals = [row_to_dict(r) for r in proposal_rows]
        
        # Собираем текст всех предложений (даже если не все done — берём что есть)
        proposals_text = []
        for i, p in enumerate(proposals, 1):
            status = p.get("status", "?")
            agent = p.get("assigned_agent") or p.get("preferred_agent", "?")
            res = (p.get("result") or "(нет результата / ещё выполняется)").strip()
            proposals_text.append(
                f"=== ПРЕДЛОЖЕНИЕ #{i} (агент: {agent}, статус: {status}) ===\n{res}\n"
            )
        
        agg_agent = aggregator or orig_task.get("result", "").split("aggregator=")[-1].split(")")[0] if "aggregator=" in (orig_task.get("result") or "") else "grok"
        agg_agent = agg_agent.strip() or "grok"
        
        agg_id = f"{task_id[:8]}-moa-agg"
        now = now_iso()
        
        agg_title = f"[MoA Aggregate] {orig_task['title']}"
        agg_description = (
            "Вы — Aggregator в Mixture-of-Agents (паттерн DeepMind).\n\n"
            "ЗАДАЧА: Проанализировать несколько независимых предложений от proposer-агентов, "
            "выявить сильные стороны каждого, исправить слабые, устранить противоречия и "
            "синтезировать ЛУЧШЕЕ возможное финальное решение. Результат должен быть "
            "существенно лучше любого отдельного предложения.\n\n"
            "Оригинальная задача:\n"
            f"Title: {orig_task['title']}\n"
            f"Description: {orig_task['description']}\n\n"
            "=== ВСЕ ПРЕДЛОЖЕНИЯ ДЛЯ СИНТЕЗА ===\n\n"
            + "\n".join(proposals_text) +
            "\n=== ИНСТРУКЦИИ ПО СИНТЕЗУ ===\n"
            "1. Выдели ключевые идеи из каждого предложения.\n"
            "2. Выбери лучшие подходы/фрагменты.\n"
            "3. Улучши код/решение, добавь недостающее, убери ошибки.\n"
            "4. Предоставь полный, готовый к использованию результат (код, план, ответ).\n"
            "5. В конце кратко объясни, почему твой вариант лучше исходных.\n\n"
            "Верни только финальный синтезированный результат + краткое обоснование."
        )
        
        tags = orig_task.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json_module.loads(tags)
            except Exception:
                tags = []
        tags_agg = tags + ["moa", f"moa-{task_id[:8]}", "aggregator"]
        
        await db.execute(
            """INSERT OR REPLACE INTO tasks 
               (id, title, description, priority, complexity, preferred_agent,
                status, assigned_agent, result, git_branch, created_at, updated_at, tags, skill)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agg_id,
                agg_title,
                agg_description,
                orig_task["priority"],
                orig_task["complexity"],
                agg_agent,
                "pending",
                None,
                None,
                f"agentforge/{agg_id}",
                now,
                now,
                json_module.dumps(tags_agg, ensure_ascii=False),
                orig_task.get("skill"),
            )
        )
        await db.commit()
        
        # Диспатч агрегатора
        try:
            subprocess.Popen(
                ["curl", "-s", "-X", "POST", f"http://127.0.0.1:8080/tasks/{agg_id}/dispatch", "-o", "/dev/null"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[AgentForge MoA] Ошибка диспатча агрегатора {agg_id}: {e}")
        
        await ws_manager.notify_task_update(task_id, {
            "status": "in_progress",
            "result": f"MoA: aggregator запущен ({agg_id})",
            "moa_aggregator": {"id": agg_id, "agent": agg_agent},
        })
        
        print(f"[AgentForge MoA] Aggregator запущен для {task_id}: {agg_id} (agent={agg_agent})")
        
        return {
            "task_id": task_id,
            "aggregator_task_id": agg_id,
            "aggregator_agent": agg_agent,
            "num_proposals_collected": len(proposals),
            "message": f"Aggregator task {agg_id} запущен. После его завершения вызовите /moa/finalize",
        }
    finally:
        await db.close()


@app.post('/tasks/{task_id}/moa/finalize', tags=['MoA'])
async def moa_finalize(task_id: str):
    """
    Финализация MoA: применяет результат aggregator-агента к оригинальной задаче.
    
    Находит {id}-moa-agg, проверяет что он в хорошем статусе (done/review),
    копирует его result в оригинальную задачу, переводит в done.
    """
    db = await get_db()
    try:
        agg_id = f"{task_id[:8]}-moa-agg"
        
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (agg_id,))
        row_agg = await cursor.fetchone()
        if not row_agg:
            raise HTTPException(status_code=404, detail="Aggregator задача (moa-agg) не найдена. Сначала /moa/aggregate")
        
        agg = row_to_dict(row_agg)
        status = agg.get("status", "")
        
        if status not in ("done", "review"):
            raise HTTPException(
                status_code=400,
                detail=f"Aggregator ещё не завершён (статус: {status}). Дождитесь завершения или запустите Guardian."
            )
        
        agg_result = agg.get("result") or "(aggregator не предоставил результат)"
        agg_agent = agg.get("assigned_agent") or agg.get("preferred_agent", "aggregator")
        
        now = now_iso()
        verdict = (
            f"MoA Aggregate (by {agg_agent}): {agg_result[:500]}{'...' if len(agg_result) > 500 else ''}"
        )
        
        await db.execute(
            "UPDATE tasks SET status = ?, result = ?, assigned_agent = ?, updated_at = ? WHERE id = ?",
            ("done", verdict, agg_agent, now, task_id)
        )
        await db.commit()
        
        await ws_manager.notify_task_update(task_id, {
            "status": "done",
            "result": verdict,
            "moa_finalized_from": agg_id,
        })
        
        print(f"[AgentForge MoA] {task_id} финализирован из агрегатора {agg_id}")
        
        return {
            "task_id": task_id,
            "status": "done",
            "finalized_from": agg_id,
            "aggregator_agent": agg_agent,
            "message": "Результат MoA применён к оригинальной задаче",
        }
    finally:
        await db.close()


@app.post('/tasks/{task_id}/review', tags=['Гардиан'])
async def guardian_review(task_id: str):
    """
    Guardian Agent — автоматическая проверка результатов задачи.
    
    Проверяет:
    - Есть ли результат (result не пустой)
    - CI прошёл успешно (result не содержит 'fail')
    - Есть ли метрики времени выполнения
    - Ветка git создана
    
    Если всё ок — переводит в done.
    Если есть проблемы — остаётся в review с комментарием.
    """
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        task = row_to_dict(row)
        issues = []
        
        # Проверка 1: Есть ли результат
        if not task.get("result"):
            issues.append("Нет результата выполнения")
        
        # Проверка 2: CI не провалился
        result = task.get("result") or ""
        # Fix: точные маркеры CI провала вместо простого "fail" (ложные срабатывания на pass/fail и т.п.)
        ci_fail_markers = ["ci failed", "ci: failed", "build failed", "test failed", "pytest_fail", "cargo_fail", "clippy_fail", "compile_fail"]
        if any(m in result.lower() for m in ci_fail_markers) or "❌" in result:
            issues.append(f"CI провалился: {result}")
        
        # Проверка 3: Статус должен быть review
        if task["status"] != "review":
            issues.append(f"Задача не в статусе review (current: {task['status']})")
        
        if issues:
            # Есть проблемы — оставляем в review
            review_comment = "Guardian: " + "; ".join(issues)
            await db.execute(
                "UPDATE tasks SET result = ?, updated_at = ? WHERE id = ?",
                (review_comment, now_iso(), task_id)
            )
            await db.commit()
            return {
                "task_id": task_id,
                "verdict": "needs_attention",
                "issues": issues,
                "message": "Задача требует внимания"
            }
        else:
            # Всё ок — принимаем
            await db.execute(
                "UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE id = ?",
                ("done", result + " | Guardian: approved ✅", now_iso(), task_id)
            )
            await db.commit()
            return {
                "task_id": task_id,
                "verdict": "approved",
                "issues": [],
                "message": "Guardian одобрил задачу ✅"
            }
    finally:
        await db.close()

@app.post('/review/all', tags=['Гардиан'])
async def guardian_review_all():
    """Проверить все задачи со статусом review"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM tasks WHERE status = 'review'")
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            # Вызываем guardian_review для каждой
            result = await guardian_review(row[0])
            results.append(result)
        return {"reviewed": len(results), "results": results}
    finally:
        await db.close()

@app.post("/tasks/{task_id}/reject", response_model=TaskResponse, tags=["Гардиан"])
async def reject_task(task_id: str, reject: TaskReject):
    """
    Отклонить выполнение задачи пользователем (Human-in-the-Loop).
    Переводит задачу обратно в статус 'pending', очищает назначенного агента,
    и сохраняет фидбек в поле result.
    """
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
        
        now = now_iso()
        feedback_msg = f"[HITL Отклонено]: {reject.feedback}"
        
        await db.execute(
            "UPDATE tasks SET status = ?, assigned_agent = NULL, result = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.pending.value, feedback_msg, now, task_id),
        )
        await db.commit()
        
        print(f"[AgentForge] ❌ Задача {task_id} отклонена пользователем. Фидбек: {reject.feedback}")
        
        # Получаем обновленную задачу
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return row_to_dict(row)
    finally:
        await db.close()

# === WebSocket эндпоинты для real-time логов ===

@app.websocket("/ws/logs/{task_id}")
async def websocket_task_logs(websocket: WebSocket, task_id: str):
    """
    WebSocket эндпоинт для real-time стриминга логов конкретной задачи.
    Клиент подключается к /ws/logs/{task_id} и получает обновления при изменении задачи.
    Используйте task_id='*' для получения обновлений по всем задачам.
    """
    await ws_manager.connect(websocket, task_id)
    try:
        # Отправляем текущее состояние задачи при подключении (если не глобальный)
        if task_id != "*":
            db = await get_db()
            try:
                cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
                row = await cursor.fetchone()
                if row:
                    task_data = row_to_dict(row)
                    await websocket.send_text(json_module.dumps({
                        "type": "initial_state",
                        "task_id": task_id,
                        "data": task_data,
                    }, ensure_ascii=False))
            finally:
                await db.close()
        
        # Держим соединение открытым, слушаем ping/pong
        while True:
            data = await websocket.receive_text()
            # Поддерживаем команду ping для keep-alive
            if data == "ping":
                await websocket.send_text(json_module.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, task_id)
    except Exception as e:
        print(f"[AgentForge WS] \u26a0\ufe0f Ошибка: {e}")
        ws_manager.disconnect(websocket, task_id)


@app.websocket("/ws/logs")
async def websocket_all_logs(websocket: WebSocket):
    """
    WebSocket эндпоинт для глобальных обновлений (все задачи).
    Альтернатива /ws/logs/* — подключается к глобальному потоку.
    """
    await ws_manager.connect(websocket, task_id=None)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json_module.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, task_id=None)
    except Exception as e:
        print(f"[AgentForge WS] \u26a0\ufe0f Ошибка: {e}")
        ws_manager.disconnect(websocket, task_id=None)


@app.get("/ws/status", tags=["WebSocket"])
async def ws_status():
    """Статус WebSocket подключений"""
    return {
        "total_connections": ws_manager.count(),
        "global_connections": len(ws_manager.global_connections),
        "task_connections": {
            tid: len(conns) for tid, conns in ws_manager.active_connections.items()
        },
    }


# === Automated Failure Clustering API (taxonomy для targeted prompt/skill fixes) ===

@app.get("/analysis/failures", tags=["Analysis"])
async def get_failure_analysis(run_cluster: bool = False):
    """
    Получить таксономию ошибок агентов (failure modes).
    Опционально: ?run_cluster=1 — запустить кластеринг (HDBSCAN + LLM) перед ответом.
    Использует LanceDB + memory_helper (sentence-transformers).
    """
    import asyncio
    mh = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_helper.py")
    
    async def _run_cluster():
        def _do():
            try:
                out = subprocess.check_output(
                    [sys.executable, mh, "cluster-failures"],
                    timeout=180, stderr=subprocess.STDOUT, text=True
                )
                return json_module.loads(out)
            except Exception as e:
                return {"error": str(e)}
        return await asyncio.to_thread(_do)
    
    if run_cluster:
        report = await _run_cluster()
    else:
        report = None
    
    # Всегда возвращаем текущую taxonomy
    try:
        tax_out = subprocess.check_output(
            [sys.executable, mh, "show-taxonomy"],
            timeout=30, stderr=subprocess.STDOUT, text=True
        )
        taxonomy = json_module.loads(tax_out)
    except Exception as e:
        taxonomy = {"error": f"taxonomy read failed: {e}"}
    
    return {
        "taxonomy": taxonomy,
        "cluster_report": report,
        "note": "Use failure_modes[].suggested_prompt_fix to improve skills/*.yaml and grok_prompts",
    }


@app.post("/analysis/failures/cluster", tags=["Analysis"])
async def trigger_failure_clustering():
    """Явно запустить pipeline кластеринга failed траекторий и обновить taxonomy."""
    import asyncio
    mh = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_helper.py")
    
    def _do():
        try:
            out = subprocess.check_output(
                [sys.executable, mh, "cluster-failures"],
                timeout=180, stderr=subprocess.STDOUT, text=True
            )
            return json_module.loads(out)
        except Exception as e:
            return {"error": str(e), "stdout": getattr(e, 'output', '')}
    
    report = await asyncio.to_thread(_do)
    return report


# === Точка входа ===

if __name__ == "__main__":
    import uvicorn
    
    print("[AgentForge] 🚀 Запуск сервера очереди задач...")
    uvicorn.run(
        "task_queue:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
    )


@app.post("/tasks/pull", response_model=Optional[TaskResponse], tags=["Задачи"])
async def pull_task(agent: str):
    """
    Умный роутер с поддержкой Work-Stealing.
    Агент запрашивает задачу для себя. API ищет задачу по его специализации.
    Если подходящих задач нет, API смотрит, не завалены ли другие агенты (Work-Stealing),
    и "крадёт" задачу у них.
    """
    db = await get_db()
    try:
        # 1. Считаем текущую нагрузку на всех агентов
        cursor = await db.execute("SELECT assigned_agent, COUNT(*) as cnt FROM tasks WHERE status IN ('in_progress', 'dispatched') GROUP BY assigned_agent")
        load = {row['assigned_agent']: row['cnt'] for row in await cursor.fetchall() if row['assigned_agent']}
        
        my_load = load.get(agent, 0)
        
        # 2. Ищем задачи со статусом pending
        cursor = await db.execute("SELECT * FROM tasks WHERE status = 'pending' ORDER BY priority DESC, created_at ASC")
        rows = await cursor.fetchall()
        
        best_task = None
        stolen = False
        
        for row in rows:
            task = row_to_dict(row)
            target_agent = resolve_agent(task)
            
            # Если задача идеально подходит нам
            if target_agent == agent:
                best_task = task
                break
                
            # Если задача чужая, проверяем Work-Stealing (порог = 2)
            if target_agent != agent:
                target_load = load.get(target_agent, 0)
                if target_load >= 2 and my_load == 0:
                    best_task = task
                    stolen = True
                    break
                    
        if not best_task:
            return None
            
        task_id = best_task['id']
        now = now_iso()
        
        if stolen:
            print(f"[Work-Stealing] 🦸 Агент {agent} украл задачу {task_id} у загруженного агента!")
        
        # Обновляем статус на in_progress и назначаем текущему агенту
        await db.execute(
            "UPDATE tasks SET status = 'in_progress', assigned_agent = ?, started_at = ?, updated_at = ? WHERE id = ?",
            (agent, now, now, task_id)
        )
        await db.commit()
        
        # Возвращаем обновленную задачу
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        updated_task = row_to_dict(row)
        
        await ws_manager.notify_task_update(task_id, updated_task)
        await _notify_webhooks("status_change", updated_task)
        
        return updated_task
    finally:
        await db.close()


@app.get("/blackboard/feed", tags=["Blackboard"])
async def get_blackboard_feed():
    """Получение активности (мыслей) агентов в реальном времени."""
    import aiosqlite
    try:
        db = await aiosqlite.connect("/home/agx/planlytasksko/data/task_checkpoints.db")
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT agent, team_id, task_id, message, created_at FROM blackboard_activity ORDER BY created_at DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        await db.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return []

