import urllib.request
import urllib.error
import json
import concurrent.futures

API_URL = "http://localhost:9090/api/tasks"

def get_tasks():
    req = urllib.request.Request(f"{API_URL}?limit=5000", headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode('utf-8'))

def cancel_task(task_id):
    data = {"status": "cancelled"}
    req = urllib.request.Request(f"{API_URL}/{task_id}", data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"}, method="PATCH")
    try:
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"Error cancelling task {task_id}: {e}")
        return False

tasks = get_tasks()
load_tasks = [t for t in tasks if t.get("title", "").startswith("Load Test")]

print(f"Found {len(load_tasks)} load tasks to cancel...")

success_count = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(cancel_task, t["id"]) for t in load_tasks]
    for future in concurrent.futures.as_completed(futures):
        if future.result():
            success_count += 1

print(f"Successfully cancelled {success_count} tasks!")
