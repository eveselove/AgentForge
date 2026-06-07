import os

def update_worker_scripts():
    grok_worker_path = "/home/eveselove/agentforge/grok_worker.sh"
    grok_xai_worker_path = "/home/eveselove/agentforge/grok_xai_worker.sh"
    
    # 1. Update grok_worker.sh
    if os.path.exists(grok_worker_path):
        with open(grok_worker_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        target = 'MAX_PARALLEL=1000'
        replacement = '''# === Ресурсные лимиты (MAX_PARALLEL) ===
# Загружаем лимит из .env файла, если он существует.
# Безопасное значение по умолчанию для Erbox: MAX_PARALLEL=2.
# Это предотвращает исчерпание памяти (OOM) при компиляции тяжелых Rust-проектов.
if [ -f "/home/eveselove/agentforge/.env" ]; then
    # shellcheck disable=SC1091
    source "/home/eveselove/agentforge/.env" 2>/dev/null || true
fi
MAX_PARALLEL="${MAX_PARALLEL:-2}"'''
        
        if target in content:
            new_content = content.replace(target, replacement)
            with open(grok_worker_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Successfully updated {grok_worker_path}")
        else:
            print(f"Target not found in {grok_worker_path} (possibly already updated)")
            
    # 2. Update grok_xai_worker.sh
    if os.path.exists(grok_xai_worker_path):
        with open(grok_xai_worker_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        target = 'MAX_PARALLEL=6          # Сколько задач этот воркер может держать одновременно'
        replacement = '''# === Ресурсные лимиты (MAX_PARALLEL) ===
# Загружаем лимит из .env файла, если он существует.
# Безопасное значение по умолчанию для Erbox: MAX_PARALLEL=2.
if [ -f "/home/eveselove/agentforge/.env" ]; then
    # shellcheck disable=SC1091
    source "/home/eveselove/agentforge/.env" 2>/dev/null || true
fi
MAX_PARALLEL="${MAX_PARALLEL:-2}"'''
        
        if target in content:
            new_content = content.replace(target, replacement)
            with open(grok_xai_worker_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Successfully updated {grok_xai_worker_path}")
        else:
            print(f"Target not found in {grok_xai_worker_path} (possibly already updated)")

if __name__ == "__main__":
    update_worker_scripts()
