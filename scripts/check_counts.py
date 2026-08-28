import sqlite3

def main():
    con = sqlite3.connect("graphone_raw.db")
    cur = con.cursor()
    cur.execute("SELECT record_type, COUNT(*) FROM structured_records GROUP BY record_type ORDER BY record_type")
    rows = cur.fetchall()
    print("--- Database Row Counts (structured_records) ---")
    total = 0
    for r, c in rows:
        print(f"  {r:<16}: {c:>5} records")
        total += c
    print(f"  {'TOTAL':<16}: {total:>5} records")
    con.close()

if __name__ == "__main__":
    main()

