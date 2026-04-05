import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import psycopg2
from src.constants import (
    DB_FIELDS,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)


def build_create_table_sql() -> str:
    columns = [f"{DB_FIELDS[0]} text PRIMARY KEY"]
    columns.extend(f"{field} text" for field in DB_FIELDS[1:])
    formatted_columns = ",\n        ".join(columns)
    return (
        "CREATE TABLE IF NOT EXISTS rappel_conso_table (\n"
        f"        {formatted_columns}\n"
        "    );"
    )


def create_table():
    """
    Creates the rappel_conso table and its columns.
    """
    create_table_sql = build_create_table_sql()
    conn = psycopg2.connect(
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
    )
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(create_table_sql)
        print("Executed table creation successfully")
    except Exception as exc:
        print(f"Couldn't execute table creation due to exception: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    create_table()
