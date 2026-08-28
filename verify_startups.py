import sqlite3
import json

c = sqlite3.connect("graphone_raw.db")
c.row_factory = sqlite3.Row

rows = c.execute("""
    SELECT
        id,
        record_type,
        source_name,
        source_url,
        llm_provider_used,
        payload_json
    FROM structured_records
    WHERE record_type = 'STARTUP'
    ORDER BY id
""").fetchall()

print("STARTUP RECORD COUNT:", len(rows))

for i, row in enumerate(rows, 1):
    print(f"\n--- STARTUP {i} ---")
    print("ID:", row["id"])
    print("Source:", row["source_name"])
    print("URL:", row["source_url"])
    print("LLM:", row["llm_provider_used"])

    try:
        payload = json.loads(row["payload_json"])
        print("Entity Name:", payload.get("entityName"))
        print("Employee Count:", payload.get("employeeCount"))
        print("Description:", payload.get("description"))
    except Exception:
        print("Payload:", row["payload_json"])

c.close()
