import lancedb
db = lancedb.connect("data/lance_tasks")
print(db.open_table("tasks").schema)
