import sqlite3
import json

c = sqlite3.connect("graphone_raw.db")
c.row_factory = sqlite3.Row

rows = c.execute("""
    SELECT id, record_type, source_name, source_url, payload_json, llm_provider_used
    FROM structured_records
    WHERE record_type = 'PRODUCT'
    ORDER BY id
""").fetchall()

print("PRODUCT RECORD COUNT:", len(rows))

for row in rows:
    data = json.loads(row["payload_json"])
    print("\n--- PRODUCT ---")
    print("ID:", row["id"])
    print("Source:", row["source_name"])
    print("URL:", row["source_url"])
    print("LLM:", row["llm_provider_used"])
    print("Name:", data.get("canonical_name") or data.get("entity_name") or data.get("name"))
    print("Description:", data.get("description"))

c.close()
