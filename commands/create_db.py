import os
from urllib.parse import urlparse
from psycopg2 import sql
from db import get_connection

# Existing database to bootstrap through, since the target DB (from DATABASE_URL) doesn't exist yet.
# Defaults to "postgres" (present on any stock Postgres image); override for
# managed services that use a different always-there database (e.g. "edb_admin").
BOOTSTRAP_DB = os.getenv("BOOTSTRAP_DB", "postgres")


def create_db(args, sql_log=None):
    target_db = urlparse(os.getenv("DATABASE_URL")).path.lstrip("/")

    conn = get_connection(dbname=BOOTSTRAP_DB, sql_log=sql_log)
    conn.autocommit = True  # Enable autocommit for creating the database

    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
    database_exists = cursor.fetchone()
    cursor.close()

    if not database_exists:
        cursor = conn.cursor()
        cursor.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(target_db)))
        cursor.close()
        print("Database created.")
    else:
        print(f'Database "{target_db}" already exists.')

    conn.close()

    conn = get_connection(sql_log=sql_log)
    print("Connection is successful!")
    conn.autocommit = True

    cursor = conn.cursor()
    cursor.execute("CREATE EXTENSION IF NOT EXISTS aidb cascade;")
    cursor.execute("CREATE EXTENSION IF NOT EXISTS pgfs;")

    cursor.close()
    conn.close()
    print("Database setup completed.")
    return sql_log
