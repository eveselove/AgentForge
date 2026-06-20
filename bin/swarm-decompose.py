#!/usr/bin/env python3
import sys
import os
import json
import urllib.request

def create_task(title, description, priority="high", agent="grok"):
    url = "http://localhost:9090/api/tasks"
    data = {
        "title": title,
        "description": description,
        "priority": priority,
        "preferred_agent": agent
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req)
        print(f"✅ Spawned task: {title}")
    except Exception as e:
        print(f"❌ Failed to spawn task {title}: {e}")

def main():
    if len(sys.argv) < 3:
        print("Usage: ./bin/swarm-decompose.py \"<instruction>\" <target_dir_or_file1> [file2...]")
        print("Example: ./bin/swarm-decompose.py \"Translate comments to English\" src/")
        sys.exit(1)
    
    instruction = sys.argv[1]
    targets = sys.argv[2:]
    
    files = []
    for t in targets:
        if os.path.isfile(t):
            files.append(t)
        elif os.path.isdir(t):
            for root, dirs, filenames in os.walk(t):
                # Modify dirs in-place to prune unwanted directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('target', '__pycache__', '.venv', '.git')]
                for f in filenames:
                    # Ignore hidden files and binaries
                    if not f.startswith('.') and not f.endswith(('.pyc', '.png', '.jpg', '.so', '.rlib', '.rmeta', '.d')):
                        files.append(os.path.join(root, f))
    
    print(f"🚀 Splitting '{instruction}' into {len(files)} parallel micro-tasks for the Grok Swarm...")
    
    for f in files:
        title = f"[SWARM] {os.path.basename(f)}: {instruction[:30]}..."
        desc = f"TARGET FILE: {f}\n\nINSTRUCTION: {instruction}\n\nStrict rule: Modify ONLY this file. Make the changes lightning fast and finish."
        create_task(title, desc)
        
    print(f"🎉 Successfully blasted {len(files)} tasks to the Gateway. The swarm of 100 agents is feasting.")

if __name__ == "__main__":
    main()
