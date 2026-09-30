import os
from urllib.parse import urlparse
from psycopg2 import sql
from db import get_connection

# Existing database to bootstrap through, since the target DB (from DATABASE_URL) doesn't exist yet.
# Defaults to "postgres" (present on any stock Postgres image); override for
# managed services that use a different always-there database (e.g. "edb_admin").
BOOTSTRAP_DB = os.getenv("BOOTSTRAP_DB", "postgres")


def create_database(args=None, sql_log=None):
    """Overview tab's entry point: create the empty demo database itself,
    before anything else — no extensions, no tables yet."""
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
        print(f'Database "{target_db}" created.')
    else:
        print(f'Database "{target_db}" already exists.')

    conn.close()
    return sql_log


def create_extensions(args=None, sql_log=None):
    """Setup step 1: install aidb/pgfs into the demo database (which must
    already exist — see create_database, run from the Overview tab)."""
    target_db = urlparse(os.getenv("DATABASE_URL")).path.lstrip("/")

    bootstrap_conn = get_connection(dbname=BOOTSTRAP_DB, sql_log=sql_log)
    bootstrap_conn.autocommit = True
    with bootstrap_conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
        database_exists = cursor.fetchone()
    bootstrap_conn.close()

    if not database_exists:
        raise RuntimeError(
            f'Database "{target_db}" doesn\'t exist yet — go to the Overview tab '
            'and click "Create database" first.'
        )

    conn = get_connection(sql_log=sql_log)
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS aidb cascade;")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pgfs;")
    conn.close()
    print("aidb/pgfs extensions installed.")
    return sql_log
