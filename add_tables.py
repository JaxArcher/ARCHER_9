import sqlite3

conn = sqlite3.connect('data/archer.db')
with open('database_schema_additions.sql', 'r') as f:
    sql = f.read()
    conn.executescript(sql)
conn.commit()
conn.close()
print('Tables added successfully!')
