import os
import psycopg2.extras
from db import get_connection

NIM_MODEL_NAME = "text-nim-embeddings"
# nvidia/nv-embedqa-e5-v5 (this demo's original model) reached end-of-life on
# NVIDIA's side on 2026-08-25 (HTTP 410 Gone). Override via env if NVIDIA
# retires this one too — check current models with a GET to
# https://integrate.api.nvidia.com/v1/models (Bearer $NVIDIA_API_KEY).
NIM_EMBEDDINGS_MODEL = os.getenv("NIM_EMBEDDINGS_MODEL") or "nvidia/nemotron-3-embed-1b"
COMPLETIONS_MODEL_NAME = "llama-nim"
# meta/llama-3.1-8b-instruct (this demo's original model) reached end-of-life
# on 2026-08-26 (HTTP 410 Gone). nvidia/nemotron-3-super-120b-a12b is a
# currently-working replacement, confirmed against a live account — but
# NVIDIA's free-tier NIM endpoint for it is intermittently overloaded (503),
# so an occasional chat/setup retry may be needed. Override via env if
# NVIDIA retires this one too.
NIM_COMPLETIONS_MODEL = os.getenv("NIM_COMPLETIONS_MODEL") or "nvidia/nemotron-3-super-120b-a12b"
BUCKET_STORAGE_LOCATION = "workshop_bucket"

# S3-compatible storage location for the catalogs volume. Defaults target the
# RustFS container from docker-compose.yml; override CATALOGS_BUCKET_URI /
# S3_* to point at real AWS S3 instead (leave S3_ENDPOINT unset for AWS).
BUCKET_URI = os.getenv("CATALOGS_BUCKET_URI", "s3://aidb-demo-catalogs")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ENDPOINT = os.getenv("S3_ENDPOINT")  # e.g. http://rustfs:9000 ; unset = AWS S3
S3_ALLOW_HTTP = os.getenv("S3_ALLOW_HTTP", "false")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")

CATALOGS_PREFIX = "aidb-demo"

# Default queries for the retrieval demo steps — chosen to match real rows in
# data/customer_feedback.csv and data/acme_product_catalog.pdf, so the first
# click already returns something meaningful. Both are user-editable in the
# dashboard.
DEFAULT_FEEDBACK_QUERY = "mobile app crashes"
DEFAULT_CATALOG_QUERY = "savings account interest rate"


def storage_location_options():
    # pgfs.create_storage_location's `options` argument, per
    # https://www.enterprisedb.com/docs/pg_extensions/pgfs/using/s3.mdx
    options = {"region": S3_REGION}
    if S3_ENDPOINT:
        options["endpoint"] = S3_ENDPOINT
    if S3_ALLOW_HTTP.lower() == "true":
        options["allow_http"] = "true"
    if not S3_ACCESS_KEY_ID:
        # No credentials configured: only works against a public/unsigned bucket.
        options["skip_signature"] = "true"
    return options


def storage_location_credentials():
    if not S3_ACCESS_KEY_ID:
        return None
    return {
        "access_key_id": S3_ACCESS_KEY_ID,
        "secret_access_key": S3_SECRET_ACCESS_KEY,
    }


# ---------------------------------------------------------------------------
# Steps: list registered models, then register the NVIDIA embedding model —
# split so each has its own Run button.
# ---------------------------------------------------------------------------

def list_models(args=None, sql_log=None):
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name, provider, functions FROM aidb.models ORDER BY name;")
            existing = cursor.fetchall()
            print(f"{len(existing)} model(s) already registered:")
            for row in existing:
                print(f"  {row[0]} ({row[1]}): {row[2]}")
    conn.close()
    return sql_log


def register_embedding_model(args=None, sql_log=None):
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT aidb.create_model(
                            %s,
                            'nim_embeddings',
                            %s::jsonb,
                            %s::jsonb,
                            true
                        );""",
                (
                    NIM_MODEL_NAME,
                    psycopg2.extras.Json({
                        "url": "https://integrate.api.nvidia.com/v1/embeddings",
                        "model": NIM_EMBEDDINGS_MODEL,
                    }),
                    psycopg2.extras.Json({"api_key": os.getenv("NVIDIA_API_KEY")}),
                ),
            )
            print(f"Registered embedding model '{NIM_MODEL_NAME}' -> {NIM_EMBEDDINGS_MODEL} (NVIDIA NIM).")
    conn.close()
    return sql_log


# ---------------------------------------------------------------------------
# Step: feedback knowledge base (table source).
# ---------------------------------------------------------------------------

def create_feedback_knowledge_base(args=None, sql_log=None):
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.customer_feedback');")
            (table_exists,) = cursor.fetchone()
            if not table_exists:
                raise RuntimeError(
                    'customer_feedback table not found — run step 4 '
                    '("Seed customer_feedback") first.'
                )
            cursor.execute("SELECT count(*) FROM customer_feedback;")
            (row_count,) = cursor.fetchone()
            if row_count == 0:
                raise RuntimeError(
                    'customer_feedback is empty — run step 4 ("Seed customer_feedback") first.'
                )

            cursor.execute("SAVEPOINT before_delete_feedback_pipeline;")
            try:
                cursor.execute("SELECT aidb.delete_pipeline('feedback_pipeline');")
                cursor.execute(
                    "DROP TABLE IF EXISTS pipeline_feedback_pipeline, "
                    "pipeline_feedback_pipeline_errors, feedback_chunks CASCADE;"
                )
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT before_delete_feedback_pipeline;")
                print(f"delete_pipeline skipped: {e}")

            cursor.execute(
                """SELECT aidb.create_pipeline(
                            name => 'feedback_pipeline',
                            source => 'customer_feedback',
                            source_key_column => 'id',
                            source_data_column => 'feedback_text',
                            step_1 => 'ChunkText',
                            step_1_options => jsonb_build_object(
                                'desired_length', 100,
                                'intermediate_destination', jsonb_build_object(
                                    'enabled', true,
                                    'destination', 'feedback_chunks'
                                )
                            ),
                            step_2 => 'KnowledgeBase',
                            step_2_options => aidb.knowledge_base_config(
                                %s, 'Text',
                                vector_index => aidb.vector_index_disabled_config()
                            )
                        );""",
                (NIM_MODEL_NAME,),
            )
            cursor.execute("SELECT aidb.run_pipeline('feedback_pipeline');")
            # Live: a trigger on customer_feedback fires on INSERT/UPDATE/DELETE,
            # so new rows are embedded within seconds, no run_pipeline call needed.
            cursor.execute("SELECT aidb.update_pipeline('feedback_pipeline', auto_processing => 'Live');")
            print("feedback_pipeline created, run, and set to Live auto-processing.")
    conn.close()
    return sql_log


def retrieve_feedback_demo(args=None, sql_log=None, query=None):
    query = query or DEFAULT_FEEDBACK_QUERY
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT key, value, distance FROM aidb.retrieve_text("
                "'public.pipeline_feedback_pipeline', %s, 5);",
                (query,),
            )
            rows = cursor.fetchall()
            print(f'{len(rows)} result(s) for "{query}":')
            for key, value, distance in rows:
                print(f"  [{key}] (distance={distance:.4f}) {value}")
    conn.close()
    return sql_log


# ---------------------------------------------------------------------------
# Steps: catalog knowledge base (volume/PDF source) — split into three so
# each has its own Run button: connect storage, create+run the pipeline,
# then enable auto-processing.
# ---------------------------------------------------------------------------

def create_catalog_storage(args=None, sql_log=None):
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pgfs;")

            cursor.execute("SAVEPOINT before_storage_location;")
            try:
                credentials = storage_location_credentials()
                cursor.execute(
                    """SELECT pgfs.create_storage_location(
                                %s, %s, options => %s::json, credentials => %s::json
                            );""",
                    (
                        BUCKET_STORAGE_LOCATION,
                        BUCKET_URI,
                        psycopg2.extras.Json(storage_location_options()),
                        psycopg2.extras.Json(credentials) if credentials else None,
                    ),
                )
                cursor.execute(
                    "SELECT aidb.create_volume('catalogs_volume', %s, %s, 'Pdf');",
                    (BUCKET_STORAGE_LOCATION, CATALOGS_PREFIX),
                )
                print(f"Storage location '{BUCKET_STORAGE_LOCATION}' and volume 'catalogs_volume' created.")

                cursor.execute("SELECT * FROM aidb.list_volume_content('catalogs_volume');")
                files = cursor.fetchall()
                print(f"\ncatalogs_volume content ({len(files)} file(s)):")
                for file_name, size, last_modified in files:
                    print(f"  {file_name} ({size} bytes, modified {last_modified})")
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT before_storage_location;")
                print(f"Storage location/volume step skipped: {e}")
    conn.close()
    return sql_log


def create_catalog_pipeline(args=None, sql_log=None):
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SAVEPOINT before_volume_check;")
            try:
                cursor.execute("SELECT count(*) FROM catalogs_volume;")
                (file_count,) = cursor.fetchone()
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT before_volume_check;")
                file_count = 0
            if file_count == 0:
                raise RuntimeError(
                    "catalogs_volume is empty (or doesn't exist yet) — run step 6 "
                    '("Seed catalog PDF") and step 7 ("Connect catalog storage") first.'
                )

            cursor.execute("SAVEPOINT before_delete_pipeline;")
            try:
                cursor.execute("SELECT aidb.delete_pipeline('catalogs_pipeline');")
                # delete_pipeline only removes the pipeline definition, not its destination/intermediate
                # tables, so drop those too or run_pipeline will skip files it already processed before.
                cursor.execute(
                    "DROP TABLE IF EXISTS pipeline_catalogs_pipeline, "
                    "pipeline_catalogs_pipeline_errors, catalog_chunks CASCADE;"
                )
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT before_delete_pipeline;")
                print(f"delete_pipeline skipped: {e}")

            cursor.execute(
                """SELECT aidb.create_pipeline(
                            name => 'catalogs_pipeline',
                            source => 'catalogs_volume',
                            step_1 => 'ParsePdf',
                            step_1_options => jsonb_build_object(
                                'method', 'Structured',
                                'allow_partial_parsing', true
                            ),
                            step_2 => 'ChunkText',
                            step_2_options => jsonb_build_object(
                                'desired_length', 1000,
                                'intermediate_destination', jsonb_build_object(
                                    'enabled', true,
                                    'destination', 'catalog_chunks'
                                )
                            ),
                            step_3 => 'KnowledgeBase',
                            step_3_options => aidb.knowledge_base_config(
                                %s, 'Text',
                                -- HNSW caps out at 2000 dimensions; the current
                                -- default embedding model (see NIM_EMBEDDINGS_MODEL)
                                -- is 2048-dim, so no ANN index is built. Fine at this
                                -- demo's scale — a handful of PDFs / feedback rows.
                                vector_index => aidb.vector_index_disabled_config()
                            )
                        );""",
                (NIM_MODEL_NAME,),
            )
            cursor.execute("SELECT aidb.run_pipeline('catalogs_pipeline');")
            print("catalogs_pipeline created and run.")
    conn.close()
    return sql_log


def enable_catalog_auto_processing(args=None, sql_log=None):
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            # Volume source: files have no triggers, so a background worker polls
            # the bucket on this interval and processes new/changed files it finds.
            cursor.execute(
                "SELECT aidb.update_pipeline('catalogs_pipeline', "
                "auto_processing => 'Background', background_sync_interval => '1 minute');"
            )
            print("catalogs_pipeline set to Background auto-processing (1 min).")
    conn.close()
    return sql_log


def retrieve_catalog_demo(args=None, sql_log=None, query=None):
    query = query or DEFAULT_CATALOG_QUERY
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            # catalogs_pipeline is Volume-sourced (PDF): retrieve_text would return
            # raw PDF bytes, so matched chunks come from retrieve_key joined back
            # to the catalog_chunks intermediate table instead.
            cursor.execute(
                """WITH retrieve_key AS (
                            SELECT * FROM aidb.retrieve_key('public.pipeline_catalogs_pipeline', %s, topk => 5)
                        )
                        SELECT r.key, r.distance, c.value
                        FROM retrieve_key r
                        JOIN catalog_chunks c ON r.part_ids[1:2] = c.part_ids
                        WHERE r.part_ids[3] = 0;""",
                (query,),
            )
            rows = cursor.fetchall()
            print(f'{len(rows)} result(s) for "{query}":')
            for key, distance, value in rows:
                print(f"  [{key}] (distance={distance:.4f}) {value}")
    conn.close()
    return sql_log


# ---------------------------------------------------------------------------
# Step: chat completions model.
# ---------------------------------------------------------------------------

def register_completions_model(args=None, sql_log=None):
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT aidb.create_model(%s, 'completions', %s::jsonb, %s::jsonb, true);",
                (
                    COMPLETIONS_MODEL_NAME,
                    psycopg2.extras.Json({
                        "model": NIM_COMPLETIONS_MODEL,
                        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
                    }),
                    psycopg2.extras.Json({"api_key": os.getenv("NVIDIA_API_KEY")}),
                ),
            )
            print(f"Registered completions model '{COMPLETIONS_MODEL_NAME}' -> {NIM_COMPLETIONS_MODEL} (NVIDIA NIM).")
    conn.close()
    return sql_log
