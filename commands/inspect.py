"""Live-inspection actions for the Upload tab: watching Background/Live
auto-processing actually happen, rather than building anything new."""

from db import get_connection

SAMPLE_FEEDBACK_ROW = (
    123,
    "mobile_app",
    "Great experience with the new features!",
    "ACME Savings",
    "2023-08-15 10:30:00",
)

# Not literally the inserted row's own text — this is the same knowledge
# base, queried for an on-topic term (there's an existing "automatic savings
# feature that rounds up purchases" row in the seeded CSV) to show retrieval
# still reflects the table's current, just-updated state.
VERIFY_QUERY = "automated savings and round-up"


def list_catalog_volume(args=None, sql_log=None):
    """What files pgfs currently sees in the RustFS bucket — run again after
    uploading a new PDF to confirm it showed up before the pipeline has
    necessarily processed it yet."""
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM aidb.list_volume_content('catalogs_volume');")
            rows = cursor.fetchall()
            print(f"catalogs_volume content ({len(rows)} file(s)):")
            for file_name, size, last_modified in rows:
                print(f"  {file_name} ({size} bytes, modified {last_modified})")
    conn.close()
    return sql_log


def pipeline_metrics(args=None, sql_log=None):
    """Per-pipeline progress: source/destination record counts, status, and
    (for catalogs_pipeline) how many source files have been picked up so
    far — the number to watch climb from 1 to 2 once Background
    auto-processing finds the newly uploaded PDF."""
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM aidb.pipeline_metrics;")
            columns = [d.name for d in cursor.description]
            rows = cursor.fetchall()
            for row in rows:
                print(dict(zip(columns, row)))
    conn.close()
    return sql_log


def insert_sample_feedback(args=None, sql_log=None):
    """Live auto-processing demo for the table-sourced pipeline: insert one
    new customer_feedback row and show pipeline_feedback_pipeline's row
    count go up immediately — no run_pipeline call, no waiting, because
    Live mode attached a trigger back in Setup step 8."""
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO customer_feedback (customer_id, channel, feedback_text, product_id, timestamp) "
                "VALUES (%s, %s, %s, %s, %s);",
                SAMPLE_FEEDBACK_ROW,
            )
            print("Inserted 1 row into customer_feedback.")
            cursor.execute("SELECT count(*) FROM pipeline_feedback_pipeline;")
            (count,) = cursor.fetchone()
            print(f"pipeline_feedback_pipeline now has {count} rows.")

            cursor.execute(
                "SELECT value, distance FROM aidb.retrieve_text('public.pipeline_feedback_pipeline', %s, 5);",
                (VERIFY_QUERY,),
            )
            rows = cursor.fetchall()
            print(f'\n{len(rows)} result(s) for "{VERIFY_QUERY}":')
            for value, distance in rows:
                print(f"  (distance={distance:.4f}) {value}")
    conn.close()
    return sql_log
