import urllib.request
import urllib.error
import json
import concurrent.futures

API_URL = "http://localhost:9090/api/tasks"

def create_task(i, agent_type):
    data = {
        "title": f"Load Test {agent_type.capitalize()} #{i}",
        "description": f"Performance validation task {i} for {agent_type}",
        "preferred_agent": agent_type
    }
    req = urllib.request.Request(API_URL, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"Error creating task: {e}")
        return False

tasks_to_create = [("grok", i) for i in range(1, 201)] + [("antigravity", i) for i in range(1, 101)]

print(f"Creating {len(tasks_to_create)} tasks...")

success_count = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(create_task, num, agent) for agent, num in tasks_to_create]
    for future in concurrent.futures.as_completed(futures):
        if future.result():
            success_count += 1

print(f"Successfully created {success_count} tasks!")
