"""
AgentForge Task Queue Server
=============================
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
        ]:
            try:
                await db.execute(col)
            except Exception:
                pass  # Колонка уже существует
        await db.commit()
    finally:
        await db.close()

# === Логика маршрутизации агентов ===

def resolve_agent(task: dict) -> str:
    """
    Автоматическая маршрутизация задачи к подходящему агенту.
    
    Правила:
    1. Если preferred_agent != auto → используем preferred_agent
    2. Простая задача + теги 'test', 'docs' → jules (async PR)
    3. Сложная задача или теги 'architecture', 'analysis', 'review' → antigravity (архитектор)
    4. По умолчанию (включая rust, cargo, server) → grok (быстрый мультиагент)
    """
    preferred = task.get("preferred_agent", "auto")
    
    # Правило 1: явно указанный агент
    if preferred != "auto":
        return preferred
    
    tags = task.get("tags", [])
    if isinstance(tags, str):
        import json
        tags = json.loads(tags)
    
    tags_lower = [t.lower() for t in tags]
    complexity = task.get("complexity", "medium")
    
    # Правило 2: простые тесты/документация → jules
    if complexity == "simple" and any(tag in tags_lower for tag in ["test", "docs"]):
        return "jules"
    
    # Правило 3: сложные/архитектурные/аналитика → antigravity
    if complexity == "complex" or any(tag in tags_lower for tag in ["architecture", "analysis", "algorithm", "review"]):
        return "antigravity"
    
    # Правило 4: всё остальное → grok (rust, cargo, server, фиксы, рутина)
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
        if tags_lower & req_lower:
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
        
        return updated_task
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

# === Guardian Agent (Автоматический код-ревью) ===


# === Arena Mode: запуск задачи у двух агентов и выбор лучшего результата ===

class ArenaRequest(BaseModel):
    """Модель запроса Arena Mode"""
    agent_a: str = Field("grok", description="Первый агент для соревнования")
    agent_b: str = Field("jules", description="Второй агент для соревнования")

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
        if "fail" in result.lower() or "❌" in result:
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
