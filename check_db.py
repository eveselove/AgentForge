import sqlite3
conn = sqlite3.connect('/home/agx/agentforge/tasks.db')
for r in conn.execute('SELECT name FROM sqlite_master WHERE type=" table\'):
 print(r)
