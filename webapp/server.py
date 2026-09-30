import contextlib
import io
import os
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from commands.create_db import create_db as _create_db
from commands.create_pipelines import (
    BUCKET_STORAGE_LOCATION,
    BUCKET_URI,
    CATALOGS_PREFIX,
    COMPLETIONS_MODEL_NAME,
    DEFAULT_CATALOG_QUERY,
    DEFAULT_FEEDBACK_QUERY,
    NIM_COMPLETIONS_MODEL,
    NIM_EMBEDDINGS_MODEL,
    NIM_MODEL_NAME,
    create_catalog_pipeline as _create_catalog_pipeline,
    create_catalog_storage as _create_catalog_storage,
    create_feedback_knowledge_base as _create_feedback_kb,
    enable_catalog_auto_processing as _enable_catalog_auto_processing,
    list_models as _list_models,
    register_completions_model as _register_completions_model,
    register_embedding_model as _register_embedding_model,
    retrieve_catalog_demo as _retrieve_catalog_demo,
    retrieve_feedback_demo as _retrieve_feedback_demo,
)
from commands.reinitialize import reinitialize as _reinitialize
from commands.seed_data import (
    INITIAL_CATALOG_PDF,
    SAMPLE_UPLOAD_PDF,
    get_pdf_bytes,
    inspect_feedback_table as _inspect_feedback_table,
    seed_catalog_pdf as _seed_catalog_pdf,
    seed_feedback_table as _seed_feedback_table,
    upload_pdf,
    upload_sample_pdf,
)
from db import get_connection
from rag import rag_query

load_dotenv()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="aidb RAG Demo")

_completions_model_ready = False


def with_retries(fn, attempts=3, delay_seconds=4):
    # NVIDIA's shared free-tier NIM endpoints intermittently return
    # HTTP 503 "Service temporarily overloaded" — observed directly against
    # this demo's completions model. Retrying a couple of times clears it.
    last_error = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
    raise last_error


def run_captured(fn, **kwargs):
    """Run a CLI-style command function, capturing its prints and the real
    SQL it executed (see db.py's LoggingCursor) so the dashboard can show
    both — the same output the CLI would print, plus the actual statements
    behind it."""
    buf = io.StringIO()
    sql_log = []
    try:
        with contextlib.redirect_stdout(buf):
            fn(None, sql_log=sql_log, **kwargs)
        return {"ok": True, "output": buf.getvalue(), "sql": sql_log}
    except Exception as e:
        return {"ok": False, "output": buf.getvalue(), "sql": sql_log, "error": str(e)}


def _demo_db_name():
    return urlparse(os.getenv("DATABASE_URL", "")).path.lstrip("/") or "demo"


# ---------------------------------------------------------------------------
# Static SQL previews — shown immediately (before anything runs) so the SQL
# can be read ahead of clicking "Run". Hand-written from the same constants
# the real functions use (commands/create_pipelines.py, commands/seed_data.py),
# living right next to those imports above so they're easy to keep in sync.
# Credential values are pre-redacted the same way db.py's real SQL log
# redacts them post-execution.
# ---------------------------------------------------------------------------

SETUP_STEPS = [
    {
        "id": "create-extensions",
        "n": 1,
        "title": "Create extensions",
        "description": "Creates the empty database and installs aidb/pgfs. Nothing else exists yet.",
        "sql": [
            f"CREATE DATABASE {_demo_db_name()};",
            "CREATE EXTENSION IF NOT EXISTS aidb CASCADE;",
            "CREATE EXTENSION IF NOT EXISTS pgfs;",
        ],
    },
    {
        "id": "list-models",
        "n": 2,
        "title": "List models",
        "description": "Shows what's already registered in aidb's model catalog — built-in local models (bert, clip, t5, llama.cpp variants), before any NVIDIA NIM model is added.",
        "sql": [
            "SELECT name, provider, functions FROM aidb.models ORDER BY name;",
        ],
    },
    {
        "id": "register-embedding-model",
        "n": 3,
        "title": "Add NVIDIA embedding model",
        "description": "Registers the NVIDIA NIM embedding model used by both knowledge bases below.",
        "sql": [
            f"""SELECT aidb.create_model(
    '{NIM_MODEL_NAME}',
    'nim_embeddings',
    '{{"url": "https://integrate.api.nvidia.com/v1/embeddings", "model": "{NIM_EMBEDDINGS_MODEL}"}}'::jsonb,
    '{{"api_key": "***REDACTED***"}}'::jsonb,
    true
);""",
        ],
    },
    {
        "id": "seed-feedback-table",
        "n": 4,
        "title": "Seed customer_feedback",
        "description": "Creates the table and loads it from the bundled CSV — first run only, a second run is a no-op.",
        "sql": [
            "CREATE TABLE IF NOT EXISTS customer_feedback (id SERIAL, customer_id INT, channel TEXT, feedback_text TEXT, product_id TEXT, timestamp TIMESTAMP);",
            "SELECT count(*) FROM customer_feedback;",
            "COPY customer_feedback (customer_id, channel, feedback_text, product_id, timestamp) FROM 'customer_feedback.csv' WITH (FORMAT csv, HEADER true);",
        ],
    },
    {
        "id": "inspect-feedback-table",
        "n": 5,
        "title": "Inspect customer_feedback",
        "description": "Read-only: shows the table's columns and a sample of rows.",
        "sql": [
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'customer_feedback' ORDER BY ordinal_position;",
            "SELECT id, channel, feedback_text, product_id FROM customer_feedback ORDER BY id LIMIT 5;",
        ],
    },
    {
        "id": "seed-catalog-pdf",
        "n": 6,
        "title": "Seed catalog PDF",
        "description": "Uploads exactly one catalog PDF to MinIO — small on purpose, the second PDF is held back for the Upload tab — then shows it inline.",
        "sql": [
            f"-- (not SQL) upload {INITIAL_CATALOG_PDF} to s3://{{bucket}}/{CATALOGS_PREFIX}/",
        ],
    },
    {
        "id": "create-catalog-storage",
        "n": 7,
        "title": "Connect catalog storage",
        "description": "Points pgfs at the MinIO bucket, creates the catalogs_volume foreign table over it, then lists what's actually in it.",
        "sql": [
            f"""SELECT pgfs.create_storage_location(
    '{BUCKET_STORAGE_LOCATION}', '{BUCKET_URI}',
    options => '{{"region": "us-east-1", "endpoint": "...", "allow_http": "true"}}'::json,
    credentials => '{{"access_key_id": "***REDACTED***", "secret_access_key": "***REDACTED***"}}'::json
);""",
            f"SELECT aidb.create_volume('catalogs_volume', '{BUCKET_STORAGE_LOCATION}', '{CATALOGS_PREFIX}', 'Pdf');",
            "SELECT * FROM aidb.list_volume_content('catalogs_volume');",
        ],
    },
    {
        "id": "create-feedback-kb",
        "n": 8,
        "title": "Create feedback knowledge base",
        "description": "Builds feedback_pipeline: chunks + embeds customer_feedback.feedback_text, then sets it to Live auto-processing.",
        "sql": [
            f"""SELECT aidb.create_pipeline(
    name => 'feedback_pipeline',
    source => 'customer_feedback',
    source_key_column => 'id',
    source_data_column => 'feedback_text',
    step_1 => 'ChunkText',
    step_1_options => jsonb_build_object('desired_length', 100, 'intermediate_destination', jsonb_build_object('enabled', true, 'destination', 'feedback_chunks')),
    step_2 => 'KnowledgeBase',
    step_2_options => aidb.knowledge_base_config('{NIM_MODEL_NAME}', 'Text', vector_index => aidb.vector_index_disabled_config())
);""",
            "SELECT aidb.run_pipeline('feedback_pipeline');",
            "SELECT aidb.update_pipeline('feedback_pipeline', auto_processing => 'Live');",
        ],
    },
    {
        "id": "retrieve-feedback",
        "n": 9,
        "title": "retrieve_text on feedback knowledge base",
        "description": "Table-sourced pipelines resolve matched chunks straight from the source column via retrieve_text.",
        "sql": [
            "SELECT key, value, distance FROM aidb.retrieve_text('public.pipeline_feedback_pipeline', '{query}', 5);",
        ],
        "needs_query": True,
        "default_query": DEFAULT_FEEDBACK_QUERY,
    },
    {
        "id": "create-catalog-pipeline",
        "n": 10,
        "title": "Create catalog pipeline",
        "description": "Builds catalogs_pipeline over catalogs_volume: parses + chunks + embeds the PDF(s), then runs it once.",
        "sql": [
            f"""SELECT aidb.create_pipeline(
    name => 'catalogs_pipeline',
    source => 'catalogs_volume',
    step_1 => 'ParsePdf',
    step_1_options => jsonb_build_object('method', 'Structured', 'allow_partial_parsing', true),
    step_2 => 'ChunkText',
    step_2_options => jsonb_build_object('desired_length', 1000, 'intermediate_destination', jsonb_build_object('enabled', true, 'destination', 'catalog_chunks')),
    step_3 => 'KnowledgeBase',
    step_3_options => aidb.knowledge_base_config('{NIM_MODEL_NAME}', 'Text', vector_index => aidb.vector_index_disabled_config())
);""",
            "SELECT aidb.run_pipeline('catalogs_pipeline');",
        ],
    },
    {
        "id": "enable-catalog-auto-processing",
        "n": 11,
        "title": "Enable catalog auto-processing",
        "description": "Volume sources have no triggers, so a background worker polls the bucket on this interval and processes new/changed files it finds.",
        "sql": [
            "SELECT aidb.update_pipeline('catalogs_pipeline', auto_processing => 'Background', background_sync_interval => '1 minute');",
        ],
    },
    {
        "id": "retrieve-catalog",
        "n": 12,
        "title": "retrieve_key on catalog knowledge base",
        "description": "Volume-sourced pipelines' retrieve_text would return raw PDF bytes, so matched chunks come from retrieve_key joined back to the catalog_chunks intermediate table instead.",
        "sql": [
            """WITH retrieve_key AS (
    SELECT * FROM aidb.retrieve_key('public.pipeline_catalogs_pipeline', '{query}', topk => 5)
)
SELECT r.key, r.distance, c.value
FROM retrieve_key r
JOIN catalog_chunks c ON r.part_ids[1:2] = c.part_ids
WHERE r.part_ids[3] = 0;""",
        ],
        "needs_query": True,
        "default_query": DEFAULT_CATALOG_QUERY,
    },
    {
        "id": "register-completions-model",
        "n": 13,
        "title": "Add chat completions NVIDIA model",
        "description": "Registers the model the Chat tab uses to generate answers from retrieved context.",
        "sql": [
            f"""SELECT aidb.create_model(
    '{COMPLETIONS_MODEL_NAME}',
    'completions',
    '{{"model": "{NIM_COMPLETIONS_MODEL}", "url": "https://integrate.api.nvidia.com/v1/chat/completions"}}'::jsonb,
    '{{"api_key": "***REDACTED***"}}'::jsonb,
    true
);""",
        ],
    },
]


@app.get("/api/health")
def health():
    return {"status": "ok"}


REINITIALIZE_SQL = [
    "DROP EXTENSION IF EXISTS aidb CASCADE;",
    "DROP EXTENSION IF EXISTS pgfs CASCADE;",
    "DROP TABLE IF EXISTS pipeline_feedback_pipeline, pipeline_feedback_pipeline_errors, feedback_chunks CASCADE;",
    "DROP TABLE IF EXISTS pipeline_catalogs_pipeline, pipeline_catalogs_pipeline_errors, catalog_chunks CASCADE;",
    "-- plus any aidb_pipeline_state_<n> bookkeeping tables auto-processing left behind:\n"
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'aidb\\_pipeline\\_state\\_%';\n"
    "DROP TABLE IF EXISTS <each found table> CASCADE;",
]


@app.get("/api/setup/steps")
def setup_steps():
    # Read-only, no DB touched: lets the dashboard show every step's SQL
    # before the user runs anything.
    return {
        "steps": SETUP_STEPS,
        "reinitialize": {
            "title": "Reset to starting point",
            "description": "Drops aidb/pgfs and everything a pipeline created on top of them. "
            "Keeps customer_feedback (table + rows) and the uploaded catalog PDF(s) in MinIO — "
            "re-run steps 1-3, 5, and 7-13 afterwards; steps 4 and 6 (seeding) aren't needed again.",
            "sql": REINITIALIZE_SQL,
        },
    }


@app.get("/api/status")
def status():
    result = {"db_connected": False, "extensions": [], "pipelines": [], "feedback_rows": None, "catalog_files": None}
    try:
        conn = get_connection()
        # Autocommit: several of these queries expect tables/views that may
        # not exist yet (e.g. before Setup has run, or after Reinitialize).
        # Without autocommit, one failed statement would abort the
        # transaction and poison every query after it. Deliberately NOT
        # wrapped in `with conn:` — psycopg2's connection context manager
        # forces a real transaction open on the first statement regardless
        # of autocommit (confirmed directly: conn.get_transaction_status()
        # goes to INTRANS, not IDLE), which defeats the point of setting it.
        conn.autocommit = True
        with conn.cursor() as cur:
            result["db_connected"] = True
            cur.execute(
                "SELECT extname FROM pg_extension WHERE extname IN ('aidb', 'pgfs', 'vector') ORDER BY extname;"
            )
            result["extensions"] = [row[0] for row in cur.fetchall()]
            try:
                cur.execute(
                    "SELECT name, source, destination, auto_processing::text "
                    "FROM aidb.pipelines ORDER BY name;"
                )
                result["pipelines"] = [
                    {"name": r[0], "source": r[1], "destination": r[2], "auto_processing": r[3]}
                    for r in cur.fetchall()
                ]
            except Exception:
                result["pipelines"] = []
            try:
                cur.execute("SELECT count(*) FROM customer_feedback;")
                result["feedback_rows"] = cur.fetchone()[0]
            except Exception:
                pass
            try:
                cur.execute("SELECT count(*) FROM catalogs_volume;")
                result["catalog_files"] = cur.fetchone()[0]
            except Exception:
                pass
        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result


@app.post("/api/setup/create-extensions")
def setup_create_extensions():
    return run_captured(_create_db)


@app.post("/api/setup/list-models")
def setup_list_models():
    return run_captured(_list_models)


@app.post("/api/setup/register-embedding-model")
def setup_register_embedding_model():
    return run_captured(_register_embedding_model)


@app.post("/api/setup/seed-feedback-table")
def setup_seed_feedback_table():
    return run_captured(_seed_feedback_table)


@app.post("/api/setup/inspect-feedback-table")
def setup_inspect_feedback_table():
    return run_captured(_inspect_feedback_table)


@app.post("/api/setup/seed-catalog-pdf")
def setup_seed_catalog_pdf():
    return run_captured(_seed_catalog_pdf)


@app.post("/api/setup/create-feedback-kb")
def setup_create_feedback_kb():
    return run_captured(_create_feedback_kb)


class RetrieveRequest(BaseModel):
    query: str | None = None


@app.post("/api/setup/retrieve-feedback")
def setup_retrieve_feedback(req: RetrieveRequest):
    return run_captured(_retrieve_feedback_demo, query=req.query)


@app.post("/api/setup/create-catalog-storage")
def setup_create_catalog_storage():
    return run_captured(_create_catalog_storage)


@app.post("/api/setup/create-catalog-pipeline")
def setup_create_catalog_pipeline():
    return run_captured(_create_catalog_pipeline)


@app.post("/api/setup/enable-catalog-auto-processing")
def setup_enable_catalog_auto_processing():
    return run_captured(_enable_catalog_auto_processing)


@app.post("/api/setup/retrieve-catalog")
def setup_retrieve_catalog(req: RetrieveRequest):
    return run_captured(_retrieve_catalog_demo, query=req.query)


@app.post("/api/setup/register-completions-model")
def setup_register_completions_model():
    global _completions_model_ready
    result = run_captured(_register_completions_model)
    if result["ok"]:
        _completions_model_ready = True
    return result


@app.post("/api/setup/reinitialize")
def setup_reinitialize():
    global _completions_model_ready
    result = run_captured(_reinitialize)
    if result["ok"]:
        # The completions model was just dropped along with the aidb
        # extension — the in-memory "already registered" flag would
        # otherwise let Chat skip re-registering it and fail.
        _completions_model_ready = False
    return result


@app.get("/api/catalog-pdf/{filename}")
def catalog_pdf(filename: str):
    data = get_pdf_bytes(filename)
    return Response(content=data, media_type="application/pdf")


def ensure_completions_model():
    # Setup step 10 registers this explicitly; this is just a safety net in
    # case someone jumps straight to Chat without running Setup in order.
    global _completions_model_ready
    if _completions_model_ready:
        return
    with_retries(lambda: _register_completions_model(sql_log=[]))
    _completions_model_ready = True


class ChatRequest(BaseModel):
    message: str
    topk: int = 20


@app.post("/api/chat")
def chat(req: ChatRequest):
    ensure_completions_model()
    answer = with_retries(
        lambda: rag_query(aidb_model_name=COMPLETIONS_MODEL_NAME, query=req.message, topk=req.topk)
    )
    return {"answer": answer}


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    key = upload_pdf(file.filename, file.file)
    return {"ok": True, "key": key}


@app.post("/api/upload-sample")
def upload_sample():
    # One-click alternative to picking a file: uploads the second bundled
    # catalog PDF straight from the container, so anyone can see Background
    # auto-processing pick up a new file without needing their own PDF handy.
    key = upload_sample_pdf()
    return {"ok": True, "key": key, "filename": SAMPLE_UPLOAD_PDF}


class SqlRequest(BaseModel):
    sql: str


@app.post("/api/sql")
def run_sql(req: SqlRequest):
    # Free-form SQL console at the bottom of the Setup tab — this is a local
    # demo tool already trusted with the same Postgres credentials, so no
    # additional access control beyond what get_connection() already has.
    # One statement per call: autocommit, so each request takes effect (or
    # fails) independently, same as typing into psql one line at a time.
    conn = get_connection()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(req.sql)
            if cur.description:
                columns = [d.name for d in cur.description]
                rows = [[None if v is None else str(v) for v in row] for row in cur.fetchall()]
                return {"ok": True, "columns": columns, "rows": rows, "rowcount": None}
            return {"ok": True, "columns": [], "rows": [], "rowcount": cur.rowcount}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


# Mounted last: Starlette matches routes in insertion order, so the API routes
# above take priority and this only catches everything else (serving
# static/index.html at "/" via html=True).
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
