#!/usr/bin/env python3
"""
AgentForge RAG Indexer — индексация логов в LanceDB
====================================================
Индексирует лог-файлы из ~/agentforge/logs/ в LanceDB для
семантического поиска по истории выполнения задач.

Использование:
    python3 rag_indexer.py              # Индексация всех логов
    python3 rag_indexer.py --search "баг парсера"  # Поиск по логам
    python3 rag_indexer.py --reindex     # Полная переиндексация
    python3 rag_indexer.py --stats       # Статистика индекса

Логи разбиваются на чанки (~500 символов) и сохраняются
с эмбеддингами для быстрого семантического поиска.
"""

import os
import sys
import glob
import hashlib
import argparse
from datetime import datetime

import lancedb
from sentence_transformers import SentenceTransformer

# === Конфигурация ===
LOGS_DIR = os.path.expanduser("~/agentforge/logs")
DB_PATH = os.path.expanduser("~/lance_data")
TABLE_NAME = "agentforge_logs"
MODEL_NAME = "all-MiniLM-L6-v2"
CHUNK_SIZE = 500          # Символов на чанк
CHUNK_OVERLAP = 50        # Перекрытие между чанками
BATCH_SIZE = 32           # Размер батча для эмбеддинга

# === Глобальная модель (ленивая инициализация) ===
_model = None

def get_model():
    """Получить или инициализировать модель эмбеддинга"""
    global _model
    if _model is None:
        print(f"[RAG] Загрузка модели {MODEL_NAME}...")
        _model = SentenceTransformer(MODEL_NAME)
        print(f"[RAG] Модель загружена")
    return _model


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Разбивает текст на чанки фиксированного размера с перекрытием.
    Старается разделять по переносам строк, чтобы не рвать контекст.
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        # Ищем ближайший перенос строки для аккуратного разрыва
        if end < len(text):
            newline_pos = text.rfind("\n", start + chunk_size // 2, end + 50)
            if newline_pos != -1:
                end = newline_pos + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Следующий чанк начинается с перекрытием
        start = end - overlap if end < len(text) else end

    return chunks


def extract_task_id(filename: str) -> str:
    """
    Извлекает task_id из имени лог-файла.
    Формат: grok_TASKID.log, jules_TASKID.log, и т.д.
    """
    basename = os.path.basename(filename)
    name_no_ext = os.path.splitext(basename)[0]
    parts = name_no_ext.split("_", 1)
    if len(parts) == 2:
        return parts[1]
    return name_no_ext


def extract_agent(filename: str) -> str:
    """Извлекает имя агента из имени лог-файла"""
    basename = os.path.basename(filename)
    parts = basename.split("_", 1)
    return parts[0] if parts else "unknown"


def compute_file_hash(filepath: str) -> str:
    """Вычисляет MD5-хеш файла для отслеживания изменений"""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            hasher.update(block)
    return hasher.hexdigest()


def get_indexed_hashes(db) -> dict[str, str]:
    """
    Получает словарь {filename: hash} уже проиндексированных файлов.
    Позволяет пропускать неизменённые логи при повторной индексации.
    """
    if TABLE_NAME not in db.table_names():
        return {}

    table = db.open_table(TABLE_NAME)
    try:
        # Получаем уникальные пары filename + file_hash
        df = table.to_pandas()[["filename", "file_hash"]].drop_duplicates()
        return dict(zip(df["filename"], df["file_hash"]))
    except Exception:
        return {}


def index_logs(reindex: bool = False):
    """
    Основная функция индексации логов в LanceDB.

    Алгоритм:
    1. Сканирует директорию логов на *.log файлы
    2. Фильтрует уже проиндексированные (по хешу файла)
    3. Разбивает каждый лог на чанки
    4. Вычисляет эмбеддинги батчами
    5. Сохраняет в LanceDB таблицу
    """
    if not os.path.exists(LOGS_DIR):
        print(f"[RAG] Директория логов не найдена: {LOGS_DIR}")
        return

    # Находим все лог-файлы
    log_files = sorted(glob.glob(os.path.join(LOGS_DIR, "*.log")))
    if not log_files:
        print("[RAG] Лог-файлы не найдены")
        return

    print(f"[RAG] Найдено {len(log_files)} лог-файлов")

    # Подключаемся к LanceDB
    os.makedirs(DB_PATH, exist_ok=True)
    db = lancedb.connect(DB_PATH)

    # Получаем хеши уже проиндексированных файлов
    if reindex:
        # При полной переиндексации удаляем старую таблицу
        if TABLE_NAME in db.table_names():
            db.drop_table(TABLE_NAME)
            print("[RAG] Старый индекс удалён (режим reindex)")
        indexed_hashes = {}
    else:
        indexed_hashes = get_indexed_hashes(db)

    # Собираем данные для индексации
    all_chunks = []
    skipped = 0
    errors = 0

    for log_file in log_files:
        filename = os.path.basename(log_file)
        file_hash = compute_file_hash(log_file)

        # Пропускаем неизменённые файлы
        if indexed_hashes.get(filename) == file_hash:
            skipped += 1
            continue

        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            if not content.strip():
                skipped += 1
                continue

            # Метаданные из имени файла
            task_id = extract_task_id(log_file)
            agent = extract_agent(log_file)
            file_size = os.path.getsize(log_file)
            modified_at = datetime.fromtimestamp(os.path.getmtime(log_file)).isoformat()

            # Разбиваем на чанки
            chunks = chunk_text(content)

            for i, chunk in enumerate(chunks):
                all_chunks.append({
                    "text": chunk,
                    "filename": filename,
                    "task_id": task_id,
                    "agent": agent,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "file_size": file_size,
                    "file_hash": file_hash,
                    "modified_at": modified_at,
                    "indexed_at": datetime.now().isoformat(),
                })

            print(f"  📄 {filename}: {len(chunks)} чанков ({file_size} байт)")

        except Exception as e:
            print(f"  ❌ Ошибка чтения {filename}: {e}")
            errors += 1

    if not all_chunks:
        print(f"[RAG] Нет новых данных для индексации (пропущено: {skipped})")
        return

    # Вычисляем эмбеддинги батчами
    print(f"[RAG] Вычисление эмбеддингов для {len(all_chunks)} чанков...")
    model = get_model()
    texts = [c["text"] for c in all_chunks]

    # Батчевое кодирование для экономии памяти
    all_vectors = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        vectors = model.encode(batch, show_progress_bar=False)
        all_vectors.extend(vectors.tolist())
        if (i + BATCH_SIZE) % 100 == 0:
            print(f"  ... обработано {min(i + BATCH_SIZE, len(texts))}/{len(texts)}")

    # Добавляем векторы в данные
    for chunk, vector in zip(all_chunks, all_vectors):
        chunk["vector"] = vector

    # Сохраняем в LanceDB
    if TABLE_NAME in db.table_names():
        table = db.open_table(TABLE_NAME)
        # Удаляем старые чанки обновлённых файлов
        updated_files = set(c["filename"] for c in all_chunks)
        for fname in updated_files:
            try:
                table.delete(f"filename = '{fname}'")
            except Exception:
                pass
        # Добавляем новые чанки
        table.add(all_chunks)
        print(f"[RAG] ✅ Обновлено {len(all_chunks)} чанков в таблице '{TABLE_NAME}'")
    else:
        db.create_table(TABLE_NAME, data=all_chunks)
        print(f"[RAG] ✅ Создана таблица '{TABLE_NAME}' с {len(all_chunks)} чанками")

    # Итоговая статистика
    print(f"\n[RAG] Итого:")
    print(f"  📊 Проиндексировано: {len(all_chunks)} чанков")
    print(f"  ⏭️  Пропущено: {skipped} файлов (без изменений)")
    print(f"  ❌ Ошибок: {errors}")


def search_logs(query: str, limit: int = 5):
    """
    Семантический поиск по проиндексированным логам.
    Возвращает наиболее релевантные фрагменты логов.
    """
    db = lancedb.connect(DB_PATH)
    if TABLE_NAME not in db.table_names():
        print("[RAG] Индекс пуст. Сначала запустите индексацию: python3 rag_indexer.py")
        return []

    table = db.open_table(TABLE_NAME)
    model = get_model()
    query_vector = model.encode(query).tolist()

    # Векторный поиск
    results = table.search(query_vector).limit(limit).to_list()

    if not results:
        print(f"[RAG] По запросу '{query}' ничего не найдено")
        return []

    print(f"\n[RAG] Результаты поиска по запросу: '{query}'")
    print("=" * 60)

    for i, r in enumerate(results, 1):
        dist = r.get("_distance", 0)
        print(f"\n--- Результат #{i} (расстояние: {dist:.4f}) ---")
        print(f"  Файл: {r.get('filename', '?')}")
        print(f"  Задача: {r.get('task_id', '?')}")
        print(f"  Агент: {r.get('agent', '?')}")
        print(f"  Чанк: {r.get('chunk_index', '?')}/{r.get('total_chunks', '?')}")
        print(f"  Текст:\n    {r.get('text', '')[:300]}...")

    return results


def show_stats():
    """Показать статистику индекса"""
    db = lancedb.connect(DB_PATH)
    if TABLE_NAME not in db.table_names():
        print("[RAG] Индекс пуст")
        return

    table = db.open_table(TABLE_NAME)
    df = table.to_pandas()

    total_chunks = len(df)
    unique_files = df["filename"].nunique()
    unique_tasks = df["task_id"].nunique()

    # Статистика по агентам
    agent_stats = df["agent"].value_counts().to_dict()

    print(f"\n[RAG] Статистика индекса '{TABLE_NAME}':")
    print(f"  📊 Всего чанков: {total_chunks}")
    print(f"  📄 Уникальных файлов: {unique_files}")
    print(f"  🎯 Уникальных задач: {unique_tasks}")
    print(f"  🤖 По агентам:")
    for agent, count in agent_stats.items():
        print(f"     {agent}: {count} чанков")

    # Последняя индексация
    latest = df["indexed_at"].max() if "indexed_at" in df.columns else "?"
    print(f"  🕐 Последняя индексация: {latest}")


# === Точка входа ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AgentForge RAG Indexer — индексация логов в LanceDB"
    )
    parser.add_argument(
        "--search", "-s",
        type=str,
        help="Семантический поиск по логам"
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Полная переиндексация (удаляет старый индекс)"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Показать статистику индекса"
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=5,
        help="Количество результатов поиска (по умолчанию: 5)"
    )

    args = parser.parse_args()

    if args.search:
        search_logs(args.search, limit=args.limit)
    elif args.stats:
        show_stats()
    else:
        index_logs(reindex=args.reindex)
