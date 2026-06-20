import lancedb
import pyarrow as pa

db = lancedb.connect("data/lance_tasks")
table = db.open_table("tasks")

# Add missing column 'requires_agent_review' as boolean, default false
table.add_columns({"requires_agent_review": "false"})
print("Column added!")
