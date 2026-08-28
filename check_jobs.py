import sqlite3
import json


DB_PATH = "graphone_raw.db"


def get_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' "
        "ORDER BY name"
    ).fetchall()

    return [row[0] for row in rows]


def get_columns(conn, table_name):
    rows = conn.execute(
        f'PRAGMA table_info("{table_name}")'
    ).fetchall()

    return rows


def print_table_structure(conn, table_name):
    print()
    print("=" * 70)
    print(f"TABLE: {table_name}")
    print("=" * 70)

    columns = get_columns(conn, table_name)

    if not columns:
        print("No columns found.")
        return

    for column in columns:
        column_id = column[0]
        name = column[1]
        data_type = column[2]
        not_null = column[3]
        default_value = column[4]
        primary_key = column[5]

        print(
            f"{column_id}: "
            f"{name} | "
            f"type={data_type} | "
            f"not_null={not_null} | "
            f"default={default_value} | "
            f"primary_key={primary_key}"
        )


def print_job_records(conn):
    print()
    print("=" * 70)
    print("JOB RECORDS")
    print("=" * 70)

    tables = get_tables(conn)

    for table_name in tables:
        columns = get_columns(conn, table_name)

        column_names = [column[1] for column in columns]

        if "record_type" not in column_names:
            continue

        print()
        print(f"Checking table: {table_name}")

        rows = conn.execute(
            f'SELECT * FROM "{table_name}" '
            f'WHERE record_type = ? '
            f'ORDER BY rowid DESC '
            f'LIMIT 10',
            ("JOB",)
        ).fetchall()

        print(f"Found {len(rows)} JOB records")

        for row in rows:
            print("-" * 70)

            for index, value in enumerate(row):
                column_name = column_names[index]

                print(
                    f"{column_name}: {value}"
                )


def print_recent_records(conn, table_name, limit=10):
    print()
    print("=" * 70)
    print(f"RECENT RECORDS FROM {table_name}")
    print("=" * 70)

    columns = get_columns(conn, table_name)

    if not columns:
        return

    column_names = [column[1] for column in columns]

    rows = conn.execute(
        f'SELECT * FROM "{table_name}" '
        f'ORDER BY rowid DESC '
        f'LIMIT ?',
        (limit,)
    ).fetchall()

    print(f"Rows found: {len(rows)}")

    for row_number, row in enumerate(rows, start=1):
        print()
        print(f"--- ROW {row_number} ---")

        for index, value in enumerate(row):
            column_name = column_names[index]

            # Make long JSON/text easier to read
            if isinstance(value, str) and len(value) > 1000:
                value = value[:1000] + "... [truncated]"

            print(f"{column_name}: {value}")


def main():
    print("=" * 70)
    print("GRAPHONE DATABASE CHECK")
    print("=" * 70)

    try:
        conn = sqlite3.connect(DB_PATH)

        print(f"\nDatabase: {DB_PATH}")

        # ---------------------------------------------------------
        # Tables
        # ---------------------------------------------------------

        tables = get_tables(conn)

        print("\n=== DATABASE TABLES ===")

        if not tables:
            print("No tables found.")
            conn.close()
            return

        for table_name in tables:
            print(f"- {table_name}")

        # ---------------------------------------------------------
        # Table structures
        # ---------------------------------------------------------

        print("\n=== TABLE STRUCTURES ===")

        for table_name in tables:
            print_table_structure(
                conn,
                table_name
            )

        # ---------------------------------------------------------
        # JOB records
        # ---------------------------------------------------------

        print_job_records(conn)

        # ---------------------------------------------------------
        # Recent structured records
        # ---------------------------------------------------------

        if "structured_records" in tables:
            print_recent_records(
                conn,
                "structured_records",
                limit=10
            )

        # ---------------------------------------------------------
        # Recent raw documents
        # ---------------------------------------------------------

        if "raw_documents" in tables:
            print_recent_records(
                conn,
                "raw_documents",
                limit=5
            )

        conn.close()

        print()
        print("=" * 70)
        print("DONE")
        print("=" * 70)

    except sqlite3.Error as error:
        print()
        print("DATABASE ERROR:")
        print(error)

    except Exception as error:
        print()
        print("ERROR:")
        print(error)


if __name__ == "__main__":
    main()