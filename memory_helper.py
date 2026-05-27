import sys
import os
import json
import urllib.request
import lancedb
from sentence_transformers import SentenceTransformer

DB_PATH = "/home/agx/lance_data"
TABLE_NAME = "agentforge_memory"
MODEL_NAME = "all-MiniLM-L6-v2"

# Отключаем предупреждения cpuinfo
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

_model = None
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model

def save_task(task_id: str):
    """Сохранить выполненную задачу в LanceDB векторную память"""
    try:
        # Получаем данные задачи через API
        url = f"http://localhost:8080/tasks/{task_id}"
        req = urllib.request.urlopen(url)
        task = json.loads(req.read().decode("utf-8"))
        
        if task.get("status") not in ("done", "review"):
            print(f"[Memory] Задача {task_id} еще не завершена. Статус: {task.get('status')}")
            return
            
        title = task.get("title", "")
        desc = task.get("description", "")
        result = task.get("result", "")
        
        if not title or not result:
            print("[Memory] Пропуск: пустое название или результат.")
            return
            
        # Формируем текст для эмбеддинга
        text_to_embed = f"Задача: {title}\nОписание: {desc}"
        
        # Получаем эмбеддинг
        model = get_model()
        vector = model.encode(text_to_embed).tolist()
        
        # Подключаемся к LanceDB
        os.makedirs(DB_PATH, exist_ok=True)
        db = lancedb.connect(DB_PATH)
        
        data = [{
            "id": task_id,
            "title": title,
            "description": desc,
            "result": result,
            "vector": vector
        }]
        
        if TABLE_NAME in db.table_names():
            table = db.open_table(TABLE_NAME)
            # Избегаем дубликатов по id
            table.delete(f"id = '{task_id}'")
            table.add(data)
            print(f"[Memory] ✅ Задача {task_id} обновлена в векторной памяти")
        else:
            table = db.create_table(TABLE_NAME, data=data)
            print(f"[Memory] ✅ Создана векторная таблица и добавлена задача {task_id}")
            
    except Exception as e:
        print(f"[Memory] ❌ Ошибка сохранения задачи: {e}")

def search_tasks(query: str, limit: int = 2):
    """Поиск похожих задач в памяти и вывод их результатов в формате RAG контекста"""
    try:
        db = lancedb.connect(DB_PATH)
        if TABLE_NAME not in db.table_names():
            return ""
            
        table = db.open_table(TABLE_NAME)
        model = get_model()
        query_vector = model.encode(query).tolist()
        
        # Векторный поиск
        results = table.search(query_vector).limit(limit).to_list()
        
        if not results:
            return ""
            
        context_parts = ["\n=== НАЙДЕННЫЙ ОПЫТ ИЗ ПРОШЛЫХ РЕШЕНИЙ ==="]
        for r in results:
            # LanceDB возвращает дистанцию _distance (меньше = ближе)
            dist = r.get("_distance", 1.0)
            if dist > 1.2: # Отсекаем слишком далекие результаты
                continue
            context_parts.append(
                f"Задача: {r['title']}\n"
                f"Описание: {r['description']}\n"
                f"Как было решено: {r['result']}\n"
                f"---"
            )
            
        if len(context_parts) > 1:
            return "\n".join(context_parts)
            
    except Exception as e:
        print(f"[Memory] ❌ Ошибка поиска в памяти: {e}", file=sys.stderr)
        
    return ""

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
        
    cmd = sys.argv[1]
    arg = sys.argv[2]
    
    if cmd == "save":
        save_task(arg)
    elif cmd == "search":
        print(search_tasks(arg))
