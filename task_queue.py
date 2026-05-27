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

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# === Константы ===
DB_PATH = os.path.expanduser("~/agentforge/tasks.db")
DISPATCHER_PATH = os.path.expanduser("~/agentforge/dispatcher.sh")

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

class TaskReject(BaseModel):
    """Модель отклонения задачи пользователем"""
    feedback: str = Field(..., description="Причина отклонения выполнения (фидбек)")

class TaskUpdate(BaseModel):
    """Модель для обновления задачи"""
    status: Optional[TaskStatus] = None
    result: Optional[str] = None
    assigned_agent: Optional[str] = None
    duration_seconds: Optional[float] = None

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
        
        # Миграция: добавляем поля для трекинга затрат
        for col in [
            "ALTER TABLE tasks ADD COLUMN duration_seconds REAL",
            "ALTER TABLE tasks ADD COLUMN started_at TEXT",
            "ALTER TABLE tasks ADD COLUMN completed_at TEXT",
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
                             preferred_agent, status, git_branch, created_at, updated_at, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        await db.commit()
        
        # Получаем созданную задачу для ответа
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        
        print(f"[AgentForge] 📋 Создана задача: {task_id} — {task.title}")
        return row_to_dict(row)
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
        return row_to_dict(row)
    finally:
        await db.close()

@app.post("/tasks/{task_id}/dispatch", tags=["Диспетчеризация"])
async def dispatch_task(task_id: str):
    """
    Диспетчеризация задачи — определяет подходящего агента и запускает выполнение.
    
    Использует автоматическую маршрутизацию на основе тегов, сложности и preferred_agent.
    Запускает dispatcher.sh в фоновом режиме для асинхронного выполнения.
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
        
        # Обновляем статус и назначенного агента
        now = now_iso()
        await db.execute(
            "UPDATE tasks SET status = ?, assigned_agent = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.dispatched.value, agent, now, task_id),
        )
        await db.commit()
        
        # Запускаем dispatcher.sh в фоновом режиме
        if os.path.exists(DISPATCHER_PATH):
            subprocess.Popen(
                ["bash", DISPATCHER_PATH, task_id, agent, task["description"], task["priority"]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[AgentForge] 🚀 Задача {task_id} отправлена агенту: {agent}")
        else:
            print(f"[AgentForge] ⚠️ Dispatcher не найден: {DISPATCHER_PATH}")
            print(f"[AgentForge] 📌 Задача {task_id} назначена агенту: {agent} (ручной запуск)")
        
        return {
            "task_id": task_id,
            "assigned_agent": agent,
            "status": "dispatched",
            "message": f"Задача отправлена агенту '{agent}'",
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
