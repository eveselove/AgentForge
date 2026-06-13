import sys
import os
import json
import urllib.request
import lancedb
import subprocess
from datetime import datetime, timezone
from sentence_transformers import SentenceTransformer
import numpy as np

DB_PATH = "/home/eveselove/lance_data"
TABLE_NAME = "agentforge_memory"
FAILURE_TABLE = "agentforge_failures"
TAXONOMY_PATH = os.path.expanduser("~/agentforge/failure_taxonomy.json")
MODEL_NAME = "all-MiniLM-L6-v2"

# Отключаем предупреждения cpuinfo
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


# Optional heavy deps for clustering (HDBSCAN preferred)
_hdbscan = None


def _get_hdbscan():
    global _hdbscan
    if _hdbscan is not None:
        return _hdbscan
    try:
        import hdbscan as _h

        _hdbscan = _h
        return _hdbscan
    except ImportError:
        print(
            "[FailureCluster] hdbscan not found — attempting auto-install (may take time)..."
        )
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--user", "hdbscan"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
            )
            import hdbscan as _h

            _hdbscan = _h
            print("[FailureCluster] ✅ hdbscan installed successfully")
            return _hdbscan
        except Exception as e:
            print(
                f"[FailureCluster] ⚠️ Could not install hdbscan ({e}). Falling back to sklearn DBSCAN."
            )
            return None


def save_task(task_id: str):
    """Сохранить выполненную задачу в LanceDB векторную память"""
    try:
        # Получаем данные задачи через API
        url = f"http://localhost:9090/tasks/{task_id}"
        req = urllib.request.urlopen(url)
        task = json.loads(req.read().decode("utf-8"))

        if task.get("status") not in ("done", "review"):
            print(
                f"[Memory] Задача {task_id} еще не завершена. Статус: {task.get('status')}"
            )
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

        data = [
            {
                "id": task_id,
                "title": title,
                "description": desc,
                "result": result,
                "vector": vector,
            }
        ]

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
            if dist > 1.2:  # Отсекаем слишком далекие результаты
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


# =============================================================================
# Automated Failure Clustering: таксономия ошибок агентов
# Pipeline: failed trajectories → embed (sentence-transformers) → HDBSCAN →
#           generate failure mode descriptions → update taxonomy (for prompt/skill fixes)
# =============================================================================

FAILURE_API = "http://localhost:9090/tasks?status=failed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_log_excerpt(task_id: str, max_chars: int = 3500) -> str:
    """Извлечь хвост лога задачи (самое релевантное для анализа failure)."""
    candidates = [
        f"/home/eveselove/agentforge/logs/grok_{task_id}.log",
        f"/home/eveselove/agentforge/logs/jules_{task_id}.log",
        f"/home/eveselove/agentforge/logs/agy_{task_id}.log",
        f"/home/eveselove/agentforge/logs/gemini_{task_id}.log",
    ]
    for log_path in candidates:
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if len(content) > max_chars:
                    content = content[-max_chars:]
                return content.strip()
            except Exception:
                continue
    return ""


def collect_failed_trajectories(limit: int | None = None) -> list[dict]:
    """
    Собрать все failed траектории.
    Источники: AgentForge API + детальные логи (trajectory).
    Возвращает список с полями для эмбеддинга и метаданными.
    """
    try:
        req = urllib.request.urlopen(FAILURE_API, timeout=15)
        tasks = json.loads(req.read().decode("utf-8"))
    except Exception as e:
        print(f"[FailureCluster] Не удалось получить failed tasks: {e}")
        return []

    if limit:
        tasks = tasks[:limit]

    trajectories = []
    for t in tasks:
        if t.get("status") != "failed":
            continue
        tid = t.get("id", "")
        title = t.get("title", "")
        desc = t.get("description", "")
        result = t.get("result", "")
        agent = t.get("assigned_agent", "")
        skill = t.get("skill") or "default"
        log_ex = _get_log_excerpt(tid)

        # Компактная "траектория" для эмбеддинга (семантический signature failure)
        failure_text = (
            f"FAILED TASK: {title}\n"
            f"Agent: {agent} | Skill: {skill}\n"
            f"Result: {result}\n"
            f"Description: {desc[:600]}\n"
            f"--- LOG EXCERPT (trajectory) ---\n{log_ex[-2200:]}\n"
            f"--- END ---"
        )

        trajectories.append(
            {
                "id": tid,
                "title": title,
                "description": desc,
                "result": result,
                "assigned_agent": agent,
                "skill": skill,
                "log_excerpt": log_ex[:800],
                "text_for_embed": failure_text,
                "updated_at": t.get("updated_at", ""),
            }
        )

    print(f"[FailureCluster] Собрано {len(trajectories)} failed траекторий")
    return trajectories


def _embed_texts(texts: list[str]) -> np.ndarray:
    model = get_model()
    vecs = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    # L2 normalize для лучшей работы с угловыми метриками
    norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return vecs / norms


def _heuristic_failure_mode(members: list[dict]) -> dict:
    """Эвристическое описание failure mode без LLM (на основе ключевых слов + статистика)."""
    results = " ".join(m["result"].lower() for m in members)
    all_text = " ".join(m["text_for_embed"].lower() for m in members)

    # Частые типы ошибок из CI
    error_types = []
    for et in [
        "clippy_fail",
        "test_fail",
        "build_fail",
        "pytest_fail",
        "skill_ci_fail",
        "timeout",
        "download",
        "ssl",
        "network",
        "cuda",
        "permission",
        "import",
        "assertion",
        "expected",
        "cargo",
        "rustc",
        "E0",
        "panic",
    ]:
        if et in results or et in all_text:
            error_types.append(et)

    # Самые частые агенты/skills
    agents = {}
    for m in members:
        a = m.get("assigned_agent") or "?"
        agents[a] = agents.get(a, 0) + 1
    top_agent = max(agents, key=agents.get) if agents else "?"

    # Ключевые симптомы (простой частотный)
    symptoms = []
    for kw in [
        "fail",
        "error",
        "cannot",
        "no such",
        "missing",
        "timeout",
        "refused",
        "denied",
    ]:
        if kw in all_text:
            symptoms.append(kw)

    name = " / ".join(error_types[:3]) or "Recurring agent execution failure"
    desc = (
        f"Cluster of {len(members)} failures. Top agent: {top_agent}. "
        f"Common symptoms: {', '.join(symptoms[:5])}. "
        f"Error tags: {', '.join(error_types[:4])}."
    )

    suggested = "Add explicit verification step + re-run checks after edits. Strengthen system_prompt with 'never mark done until all CI pass locally'."
    if "clippy" in error_types or "test" in error_types:
        suggested = "In skill system_prompt: 'After every code change run: cargo clippy -- -D warnings && cargo test. Only then report success.'"
    if "network" in error_types or "download" in error_types:
        suggested = "Add retry + fallback mirrors in build scripts. Or mark task as 'needs-net' and skip heavy cargo in sandbox."

    return {
        "short_name": name[:60],
        "description": desc[:280],
        "evidence": f"Examples: {', '.join(m['id'] for m in members[:3])}",
        "suggested_prompt_fix": suggested,
        "suggested_skill_change": "Consider new skill variant or extra 'verify' tag.",
        "count": len(members),
    }


def _llm_describe_cluster(members: list[dict]) -> dict | None:
    """Попытка сгенерировать описание через Grok CLI (неинтерактивно)."""
    sample = "\n\n".join(
        f"Task {m['id']}: {m['title']}\nResult: {m['result']}\nExcerpt: {m['log_excerpt'][:900]}"
        for m in members[:4]
    )
    prompt = (
        "You are an expert AI agent reliability analyst. "
        "Given the following failed agent execution trajectories, identify the SINGLE recurring FAILURE MODE (root cause pattern that can be prevented by prompt/skill change).\n\n"
        "Return ONLY a compact JSON (no prose outside):\n"
        '{"short_name": "3-7 word title", '
        '"description": "1-2 sentence root cause", '
        '"symptoms": ["list", "of", "key", "symptoms"], '
        '"suggested_prompt_fix": "exact text to add to system_prompt or skill", '
        '"suggested_skill_change": "recommendation for skills/*.yaml"}\n\n'
        f"TRAJECTORIES:\n{sample}\n\nJSON:"
    )

    try:
        # Non-interactive, time bounded call via grok CLI
        proc = subprocess.run(
            ["grok", "--always-approve", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=90,
            cwd="/tmp",
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        # Ищем JSON блок
        import re

        m = re.search(r'\{[\s\S]*?"short_name"[\s\S]*?\}', out)
        if m:
            data = json.loads(m.group(0))
            # sanitize
            return {
                "short_name": str(data.get("short_name", "LLM cluster"))[:70],
                "description": str(data.get("description", ""))[:300],
                "symptoms": data.get("symptoms", [])[:6],
                "suggested_prompt_fix": str(data.get("suggested_prompt_fix", ""))[:400],
                "suggested_skill_change": str(data.get("suggested_skill_change", ""))[
                    :300
                ],
                "count": len(members),
            }
    except Exception as e:
        print(f"[FailureCluster] LLM describe failed (fallback to heuristic): {e}")
    return None


def generate_failure_mode(cluster_id: int, members: list[dict]) -> dict:
    """Сгенерировать описание failure mode (LLM приоритет, fallback heuristic)."""
    llm = _llm_describe_cluster(members)
    if llm:
        mode = llm
        mode["source"] = "llm"
    else:
        mode = _heuristic_failure_mode(members)
        mode["source"] = "heuristic"

    mode["cluster_id"] = cluster_id
    mode["task_ids"] = [m["id"] for m in members]
    mode["representative"] = members[0]["title"] if members else ""
    mode["updated_at"] = _now_iso()
    return mode


def _load_taxonomy() -> dict:
    if os.path.exists(TAXONOMY_PATH):
        try:
            with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "version": 1,
        "last_updated": _now_iso(),
        "total_failures_analyzed": 0,
        "failure_modes": [],
        "notes": "Auto-generated by AgentForge Failure Clustering. Used to drive targeted prompt & skill improvements.",
    }


def _save_taxonomy(tax: dict):
    os.makedirs(os.path.dirname(TAXONOMY_PATH), exist_ok=True)
    tax["last_updated"] = _now_iso()
    with open(TAXONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(tax, f, ensure_ascii=False, indent=2)
    print(f"[FailureCluster] ✅ Taxonomy updated: {TAXONOMY_PATH}")


def persist_failures_to_lance(trajectories: list[dict]):
    """Сохранить (или обновить) failed trajectories в LanceDB (отдельная таблица)."""
    if not trajectories:
        return
    try:
        os.makedirs(DB_PATH, exist_ok=True)
        db = lancedb.connect(DB_PATH)
        model = get_model()

        data = []
        for t in trajectories:
            vec = model.encode(t["text_for_embed"]).tolist()
            data.append(
                {
                    "id": t["id"],
                    "title": t["title"],
                    "result": t["result"],
                    "assigned_agent": t.get("assigned_agent", ""),
                    "skill": t.get("skill", ""),
                    "failure_text": t["text_for_embed"][:2000],
                    "vector": vec,
                    "updated_at": t.get("updated_at", _now_iso()),
                }
            )

        if FAILURE_TABLE in db.table_names():
            tbl = db.open_table(FAILURE_TABLE)
            for d in data:
                tbl.delete(f"id = '{d['id']}'")
            tbl.add(data)
        else:
            db.create_table(FAILURE_TABLE, data=data)
        print(
            f"[FailureCluster] Persisted {len(data)} failures to LanceDB::{FAILURE_TABLE}"
        )
    except Exception as e:
        print(f"[FailureCluster] Lance persist error: {e}")


def save_failure(task_id: str):
    """Сохранить ОДНУ failed траекторию (вызывается из runner'ов при CI fail)."""
    try:
        url = f"http://localhost:9090/tasks/{task_id}"
        req = urllib.request.urlopen(url, timeout=10)
        task = json.loads(req.read().decode("utf-8"))

        if task.get("status") != "failed":
            print(f"[Failure] {task_id} not in failed status")
            return

        # Reuse the collector logic for single item
        trajs = collect_failed_trajectories()  # lightweight enough
        this = [t for t in trajs if t["id"] == task_id]
        if this:
            persist_failures_to_lance(this)
            print(f"[Failure] ✅ Saved failure trajectory for {task_id} to LanceDB")
        else:
            print(f"[Failure] No trajectory collected for {task_id}")
    except Exception as e:
        print(f"[Failure] save_failure error: {e}")


def cluster_failures(
    min_cluster_size: int = 2, use_llm: bool = True, limit: int | None = None
) -> dict:
    """
    Полный pipeline кластеринга failure modes.
    1. Собрать траектории
    2. Эмбед
    3. HDBSCAN (или DBSCAN fallback)
    4. Сгенерировать описания
    5. Обновить taxonomy + Lance
    """
    traj = collect_failed_trajectories(limit=limit)
    if not traj:
        return {"status": "no_failures", "message": "Нет failed задач для кластеринга"}

    persist_failures_to_lance(traj)

    texts = [t["text_for_embed"] for t in traj]
    embeddings = _embed_texts(texts)

    # Dim reduction for stability (optional, sklearn available)
    n_samples = len(embeddings)
    if n_samples > 6 and embeddings.shape[1] > 32:
        try:
            from sklearn.decomposition import PCA

            n_comp = min(30, n_samples - 1, embeddings.shape[1] - 1)
            embeddings = PCA(n_components=n_comp).fit_transform(embeddings)
        except Exception:
            pass

    # Clustering
    hdb = _get_hdbscan()
    if hdb is not None:
        try:
            clusterer = hdb.HDBSCAN(
                min_cluster_size=max(1, min_cluster_size),
                metric="euclidean",
                cluster_selection_method="eom",
                allow_single_cluster=True,
            )
            labels = clusterer.fit_predict(embeddings)
        except Exception as e:
            print(f"[FailureCluster] HDBSCAN error, fallback: {e}")
            hdb = None

    if hdb is None:
        # sklearn DBSCAN fallback (cosine-friendly via precomputed or normed)
        from sklearn.cluster import DBSCAN
        from sklearn.metrics.pairwise import cosine_distances

        # Use cosine distance for embeddings
        dists = cosine_distances(embeddings)
        eps = 0.65  # tuned for sentence embeddings
        clustering = DBSCAN(
            eps=eps, min_samples=max(1, min_cluster_size), metric="precomputed"
        )
        labels = clustering.fit_predict(dists)

    # Group members (include noise as potential singletons if very few total)
    clusters: dict[int, list] = {}
    for idx, lab in enumerate(labels):
        lab = int(lab)
        clusters.setdefault(lab, []).append(traj[idx])

    # Handle noise: if overall very small data, treat all as one cluster
    if -1 in clusters and len(clusters) == 1 and len(traj) >= 1:
        clusters[0] = clusters.pop(-1)  # promote noise to cluster 0

    failure_modes = []
    cid = 0
    for lab, members in sorted(clusters.items()):
        if lab == -1 and len(members) < 2:
            # too small outliers — still record as "uncategorized"
            mode = _heuristic_failure_mode(members)
            mode["short_name"] = "Outlier / rare failure"
            mode["cluster_id"] = -1
            mode["task_ids"] = [m["id"] for m in members]
            mode["source"] = "outlier"
            failure_modes.append(mode)
            continue
        mode = generate_failure_mode(cid, members)
        failure_modes.append(mode)
        cid += 1

    # Update taxonomy (merge intelligently by signature similarity)
    tax = _load_taxonomy()
    existing = {fm.get("short_name"): fm for fm in tax.get("failure_modes", [])}

    for new_mode in failure_modes:
        key = new_mode["short_name"]
        if key in existing:
            # refresh count + suggestions
            existing[key].update(
                {
                    "count": existing[key].get("count", 0) + new_mode.get("count", 0),
                    "task_ids": list(
                        set(
                            existing[key].get("task_ids", [])
                            + new_mode.get("task_ids", [])
                        )
                    ),
                    "suggested_prompt_fix": new_mode.get("suggested_prompt_fix")
                    or existing[key].get("suggested_prompt_fix"),
                    "updated_at": new_mode["updated_at"],
                }
            )
        else:
            existing[key] = new_mode

    tax["failure_modes"] = list(existing.values())
    tax["total_failures_analyzed"] = len(traj)
    _save_taxonomy(tax)

    return {
        "status": "ok",
        "num_failures": len(traj),
        "num_clusters": len(
            [m for m in failure_modes if m.get("cluster_id", -1) != -1]
        ),
        "num_outliers": len([m for m in failure_modes if m.get("cluster_id", 0) == -1]),
        "failure_modes": failure_modes,
        "taxonomy_path": TAXONOMY_PATH,
    }


def get_failure_taxonomy() -> dict:
    """Вернуть текущую таксономию (для использования в промптах / дашборде)."""
    tax = _load_taxonomy()
    # Обогащаем свежими данными из Lance если есть
    try:
        db = lancedb.connect(DB_PATH)
        if FAILURE_TABLE in db.table_names():
            tbl = db.open_table(FAILURE_TABLE)
            tax["lance_failure_count"] = (
                tbl.count_rows() if hasattr(tbl, "count_rows") else len(tbl.to_list())
            )
    except Exception:
        pass
    return tax


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: memory_helper.py <save|search|save-failure|cluster-failures|show-taxonomy> [arg]"
        )
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "save" and len(sys.argv) >= 3:
        save_task(sys.argv[2])
    elif cmd == "search" and len(sys.argv) >= 3:
        print(search_tasks(sys.argv[2]))
    elif cmd == "save-failure" and len(sys.argv) >= 3:
        save_failure(sys.argv[2])
    elif cmd == "cluster-failures":
        limit = (
            int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
        )
        report = cluster_failures(min_cluster_size=2, use_llm=True, limit=limit)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif cmd == "show-taxonomy":
        tax = get_failure_taxonomy()
        print(json.dumps(tax, ensure_ascii=False, indent=2))
    else:
        print(f"Unknown command or missing arg: {cmd}")
        sys.exit(1)
