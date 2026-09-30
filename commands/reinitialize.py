from psycopg2 import sql

from db import get_connection


def reinitialize(args=None, sql_log=None):
    """Reset the database back to its initial starting point.

    Keeps: the customer_feedback table (and its rows) and the catalog
    PDF(s) already uploaded to MinIO — the demo's actual source data.

    Drops: the aidb/pgfs extensions (which removes registered models,
    pipeline definitions, and storage locations/volumes) plus the
    destination/intermediate tables a pipeline run creates on top of them
    (these aren't extension member objects, so DROP EXTENSION alone doesn't
    remove them — see create_pipelines.py's create_*_knowledge_base
    functions, which drop the same tables before rebuilding a pipeline).

    After this, Setup steps 1-3, 5, and 7-13 need to run again; steps 4
    ("Seed customer_feedback") and 6 ("Seed catalog PDF") don't, since the
    data they seed is untouched.
    """
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("DROP EXTENSION IF EXISTS aidb CASCADE;")
            cursor.execute("DROP EXTENSION IF EXISTS pgfs CASCADE;")
            cursor.execute(
                "DROP TABLE IF EXISTS pipeline_feedback_pipeline, "
                "pipeline_feedback_pipeline_errors, feedback_chunks CASCADE;"
            )
            cursor.execute(
                "DROP TABLE IF EXISTS pipeline_catalogs_pipeline, "
                "pipeline_catalogs_pipeline_errors, catalog_chunks CASCADE;"
            )
            # Background/Live auto-processing also leaves internal
            # bookkeeping tables behind (aidb_pipeline_state_<n>, tracking
            # which rows/files a pipeline has already processed) — not
            # extension members either, and their numeric suffix isn't
            # predictable, so find and drop them by name pattern.
            cursor.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename LIKE 'aidb\\_pipeline\\_state\\_%';"
            )
            state_tables = [row[0] for row in cursor.fetchall()]
            for table in state_tables:
                cursor.execute(
                    sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(sql.Identifier(table))
                )
    conn.close()
    print("Dropped aidb/pgfs extensions and all pipeline-created tables.")
    print("Kept: customer_feedback (table + rows) and the uploaded catalog PDF(s) in MinIO.")
    print(
        "Re-run Setup steps 1-3, 5, and 7-13 to rebuild — steps 4 and 6 "
        "(seeding customer_feedback / the catalog PDF) are not needed again."
    )
    return sql_log
