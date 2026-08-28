import sqlite3
import json

c = sqlite3.connect("graphone_raw.db")
c.row_factory = sqlite3.Row

rows = c.execute("""
    SELECT id, source_url, payload_json, llm_provider_used
    FROM structured_records
    WHERE record_type = 'PRODUCT'
    ORDER BY id
""").fetchall()

for row in rows:
    print("\n==============================")
    print("ID:", row["id"])
    print("URL:", row["source_url"])
    print("LLM:", row["llm_provider_used"])
    print("PAYLOAD:")

    try:
        data = json.loads(row["payload_json"])
        print(json.dumps(data, indent=2))
    except Exception as e:
        print("JSON ERROR:", e)
        print(row["payload_json"])

c.close()
