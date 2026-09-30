# aidb-rag (dockerized)

A click-through, self-contained version of the `aidb`/`pgfs` RAG demo:
a chatbot for a fictional bank, ACME, that answers questions using two
knowledge bases built from data that already lives in Postgres and object
storage — no separate vector database, no separate model-serving layer.

- **Structured**: a `customer_feedback` table, chunked and embedded via an
  `aidb` pipeline (`feedback_pipeline`).
- **Unstructured**: PDF product catalogs in a MinIO bucket, parsed, chunked,
  and embedded via another pipeline (`catalogs_pipeline`).

Everything runs in Docker: Postgres 18 + `aidb` + `pgfs`, a MinIO container
standing in for S3, and a small dashboard web app to run the whole demo flow
by clicking buttons instead of typing CLI commands.

## Requirements

- Docker and Docker Compose v2 (`docker compose version` should work)
- An EDB account token (used only at build time to install `aidb`/`pgfs`
  from EDB's package repo — see [Repository information](https://www.enterprisedb.com/docs/postgres_distributed_for_kubernetes/latest/private_edb_registries/#repository-information)
  for how to get one)
- An NVIDIA API key (for embeddings and completions via NVIDIA NIM)

## Quickstart

```sh
git clone <this-repo>
cd rag-demo-docker
cp .env-example .env
# edit .env: set EDB_SUBSCRIPTION_TOKEN and NVIDIA_API_KEY

# one-time: log in so docker-compose can pull the base Postgres image
docker login docker.enterprisedb.com --username k8s --password "$EDB_SUBSCRIPTION_TOKEN"

./00-provision.sh
```

Once it's up:

| URL                            | What                                  |
|---------------------------------|----------------------------------------|
| http://localhost:8080          | Dashboard (the demo itself)            |
| http://localhost:9001          | MinIO console                          |
| postgres://postgres:postgres@localhost:5434/demo | psql / any Postgres client |

Open the dashboard and click through the **Setup** tab, in order. Every
step's SQL is shown *before* you run it (a static preview, tagged
"preview") — read it, then click Run; the block updates to the exact
statements actually executed (tagged "executed", redacted of any
credentials) plus the real output:

1. **Create extensions** — creates the empty database, installs `aidb`/`pgfs`.
   Nothing else exists yet.
2. **List models** — shows what's already registered in aidb's model catalog
   (13 built-in local models — bert, clip, t5, several llama.cpp variants),
   before any NVIDIA NIM model is added.
3. **Add NVIDIA embedding model** — registers the NVIDIA NIM embedding model
   used by both knowledge bases below.
4. **Seed customer_feedback** — creates the table and loads it from the
   bundled CSV. First run only; re-running is a no-op.
5. **Inspect customer_feedback** — read-only: shows the table's columns and a
   sample of rows.
6. **Seed catalog PDF** — uploads exactly *one* catalog PDF
   (`acme_product_catalog.pdf`) to MinIO — small on purpose, the second PDF
   is held back for the Upload tab — then shows it inline. First run only;
   re-running is a no-op.
7. **Connect catalog storage** — points `pgfs` at the MinIO bucket, creates
   the `catalogs_volume` foreign table over it, then lists what's actually in
   it with `aidb.list_volume_content`.
8. **Create feedback knowledge base** — builds `feedback_pipeline` from
   `customer_feedback` and sets it to `Live` auto-processing (a trigger fires
   on insert/update/delete).
9. **`retrieve_text` on feedback knowledge base** — a live semantic-search
   demo against real feedback rows; the query box is editable (defaults to
   "mobile app crashes").
10. **Create catalog pipeline** — builds and runs `catalogs_pipeline` over
    `catalogs_volume`. Running before step 7 (or before step 6 has uploaded a
    PDF) fails with a clear "run Seed catalog PDF / Connect catalog storage
    first" error rather than a cryptic pgfs one.
11. **Enable catalog auto-processing** — sets `catalogs_pipeline` to
    `Background` (polls the bucket every minute for new/changed files).
12. **`retrieve_key` on catalog knowledge base** — same idea against the PDF
    knowledge base (defaults to "savings account interest rate").
13. **Add chat completions NVIDIA model** — registers the model the Chat tab
    uses to generate answers from retrieved context.

At the bottom of the Setup tab, a **SQL Console** lets you run any SQL
directly against the demo database — explore `aidb.*`/`pgfs.*` catalogs,
inspect tables, or try your own queries (one statement per run, autocommit).

Then use the **Chat** tab to ask questions, and the **Upload** tab to drop in
a new PDF — or click "Use bundled sample" to upload the held-back
`acme_2026_expansion_catalog.pdf` with one click — and watch `Background`
auto-processing pick it up (check the Overview tab's catalog file count, or
just ask about it in Chat after the ~1 minute sync interval).

**Reinitialize** (top of the Setup tab, in red) resets back to the initial
starting point without tearing down any containers: it drops the `aidb`/`pgfs`
extensions, every pipeline-created table (`pipeline_feedback_pipeline`,
`pipeline_catalogs_pipeline`, `feedback_chunks`, `catalog_chunks`, their error
tables, and the `aidb_pipeline_state_<n>` auto-processing bookkeeping tables),
but *keeps* `customer_feedback` (table + rows) and the uploaded catalog
PDF(s) in MinIO. After it, steps 1-3, 5, and 7-13 rebuild everything from
that same data — steps 4 and 6 (seeding) aren't needed again.

Tear down with `./99-deprovision.sh` — there's no persistent volume by design,
so re-running `./00-provision.sh` always starts from the same known-good state.

## How it's put together

- `docker-compose.yml` runs three containers: `postgres` (Postgres+aidb+pgfs),
  `minio` (S3-compatible storage), and `webapp` (the dashboard).
- `postgres/Dockerfile` builds on EDB's own CloudNativePG operand image
  (`docker.enterprisedb.com/k8s/postgresql:18.6-standard-ubi9` — community
  Postgres 18.6 on UBI9). That base image ships bare Postgres binaries with
  no standalone entrypoint (it's designed to be driven by the CNPG operator's
  instance manager) and no `aidb`/`pgfs`, so the Dockerfile installs both from
  EDB's package repo (`edb-pg18-aidb`, `edb-pg18-pgfs`) and
  `postgres/docker-entrypoint.sh` does the `initdb`/config a real entrypoint
  would.
- `webapp/server.py` is a small FastAPI app that calls this repo's own
  `commands/create_db.py`, `commands/create_pipelines.py`, `commands/seed_data.py`,
  and `rag.py` directly — the dashboard buttons run the exact same code as the
  CLI, nothing is duplicated or mocked.
- `db.py`'s `LoggingConnection`/`LoggingCursor` capture every SQL statement a
  Setup step runs (via psycopg2's own `cursor.query`, i.e. the fully
  interpolated statement actually sent to Postgres) and redact any
  credential values before the dashboard displays them.
- `webapp/static/` is the dashboard's frontend: plain HTML/CSS/JS, no build
  step, no external UI framework (light theme with a dark header bar,
  monospace SQL/output blocks — loosely modeled on
  [ruxuez/whpg-performance's perf_demo](https://github.com/ruxuez/whpg-performance/tree/main/perf_demo);
  the Chat tab follows a ChatGPT/Claude-style layout).
- `commands/create_pipelines.py`'s storage-location config
  (`CATALOGS_BUCKET_URI`, `S3_ENDPOINT`, `S3_ALLOW_HTTP`, `S3_ACCESS_KEY_ID`,
  `S3_SECRET_ACCESS_KEY`) is env-driven so it targets MinIO by default but can
  point at real AWS S3 instead (leave `S3_ENDPOINT` unset for AWS).

## How retrieval works

`rag.py` queries both knowledge bases per question and combines the results as
context for the completion model:

- The table-sourced KB (`feedback_pipeline`) is queried with `aidb.retrieve_text`,
  which resolves matched chunks directly from the source column.
- The volume-sourced KB (`catalogs_pipeline`) is queried with `aidb.retrieve_key`,
  joined back to its `catalog_chunks` intermediate table — `retrieve_text` on a
  volume-sourced pipeline returns the raw source file bytes, not parsed text,
  so `retrieve_key` + join is required there.

## A note on NVIDIA NIM model churn

NVIDIA periodically retires NIM models (`nv-embedqa-e5-v5` and
`llama-3.1-8b-instruct`, this demo's original defaults, both went end-of-life
in August 2026). If Setup steps 2/4/6/8 or the Chat tab start failing with an
HTTP 410 "reached its end of life" error, the fix is to swap in a currently
available model:

1. List what your account can actually reach: `GET https://integrate.api.nvidia.com/v1/models`
   (Bearer `$NVIDIA_API_KEY`) lists what's *offered*, but not every listed
   model is invokable on every account/tier — some return `404 Not Found for
   account` when called. Confirm a candidate works with a direct POST to
   `/v1/embeddings` or `/v1/chat/completions` before wiring it in.
2. Override `NIM_EMBEDDINGS_MODEL` / `NIM_COMPLETIONS_MODEL` in `.env` (see
   `commands/create_pipelines.py` for the current defaults and where they're used).
3. If the new embedding model's output is >2000 dimensions, pgvector's HNSW
   index can't be used — `create_pipelines.py` already passes
   `aidb.vector_index_disabled_config()` to both knowledge bases for this
   reason, so no further change is needed there, just fine for this demo's
   scale.

Separately, some NIM models on the free tier are intermittently overloaded
(`503 Service temporarily overloaded`) under real, if light, load. `webapp/server.py`
retries completions calls a few times before giving up; if you still see
occasional chat failures, that's this, not a bug.

## Advanced: running without Docker

If you already have your own Postgres 16+ instance with `aidb`/`pgfs` and your
own S3 bucket, you can run this the original way, without docker-compose:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env-example .env   # fill in DATABASE_URL, NVIDIA_API_KEY, CATALOGS_BUCKET_URI, etc.

python app.py create-db
python app.py list-models
python app.py register-embedding-model
python app.py seed-feedback-table
python app.py inspect-feedback-table
python app.py seed-catalog-pdf
python app.py create-catalog-storage
python app.py create-feedback-kb
python app.py retrieve-feedback "mobile app crashes"
python app.py create-catalog-pipeline
python app.py enable-catalog-auto-processing
python app.py retrieve-catalog "savings account interest rate"
python app.py register-completions-model
streamlit run app.py chat
```

### Subcommands

```sh
{create-db, chat, list-models, register-embedding-model, seed-feedback-table,
 inspect-feedback-table, seed-catalog-pdf, create-feedback-kb, retrieve-feedback,
 create-catalog-storage, create-catalog-pipeline, enable-catalog-auto-processing,
 retrieve-catalog, register-completions-model, reinitialize}
  create-db                       Create the database and install aidb/pgfs extensions
  list-models                     List models already registered in aidb's model catalog
  register-embedding-model        Register the NVIDIA NIM embedding model
  seed-feedback-table             Create customer_feedback and load it from the bundled CSV (first run only)
  inspect-feedback-table          Show customer_feedback's columns and a sample of rows
  seed-catalog-pdf                Upload the initial catalog PDF to MinIO (first run only)
  create-feedback-kb              Build the feedback_pipeline knowledge base
  retrieve-feedback [query]       Demo aidb.retrieve_text against the feedback knowledge base
  create-catalog-storage          Connect pgfs to the MinIO bucket and create the catalogs_volume
  create-catalog-pipeline         Build and run the catalogs_pipeline knowledge base
  enable-catalog-auto-processing  Enable Background auto-processing on catalogs_pipeline
  retrieve-catalog [query]        Demo aidb.retrieve_key against the catalog knowledge base
  register-completions-model      Register the NVIDIA NIM chat completions model
  reinitialize                    Reset to the initial starting point (keeps customer_feedback + uploaded PDFs)
  chat                          Launch the Streamlit chat UI
```

## Updating a pipeline manually

If auto-processing isn't enabled, re-run a pipeline after its source data changes:

```sql
SELECT aidb.run_pipeline('feedback_pipeline');
```
