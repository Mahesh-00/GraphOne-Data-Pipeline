import sqlite3

c = sqlite3.connect("graphone_raw.db")
c.row_factory = sqlite3.Row

rows = c.execute("PRAGMA table_info(structured_records)").fetchall()

print("STRUCTURED_RECORDS COLUMNS:")
for row in rows:
    print(f"{row['cid']}: {row['name']} ({row['type']})")

c.close()
