import os

import boto3
from botocore.exceptions import ClientError

from commands.create_pipelines import BUCKET_URI, CATALOGS_PREFIX, S3_ENDPOINT
from db import get_connection

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CUSTOMER_FEEDBACK_CSV = os.path.join(DATA_DIR, "customer_feedback.csv")

# Only one catalog PDF is seeded up front, so the database starts from a
# realistic-but-small initial point. The second PDF is reserved for the
# dashboard's Upload tab, to demonstrate Background auto-processing picking
# up a new file live rather than everything being preloaded.
INITIAL_CATALOG_PDF = "acme_product_catalog.pdf"
SAMPLE_UPLOAD_PDF = "acme_2026_expansion_catalog.pdf"


def _bucket_name():
    # BUCKET_URI looks like "s3://bucket-name" (no path component is used here).
    return BUCKET_URI.removeprefix("s3://").split("/", 1)[0]


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT or None,
        aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )


def _seed_feedback_table(cursor):
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS customer_feedback (
                    id SERIAL NOT NULL,
                    customer_id INT,
                    channel TEXT,
                    feedback_text TEXT,
                    product_id TEXT,
                    timestamp TIMESTAMP
                );"""
    )
    cursor.execute("SELECT count(*) FROM customer_feedback;")
    (row_count,) = cursor.fetchone()
    if row_count > 0:
        print(f"customer_feedback already has {row_count} rows, skipping load.")
        return

    with open(CUSTOMER_FEEDBACK_CSV, "r") as f:
        cursor.copy_expert(
            "COPY customer_feedback (customer_id, channel, feedback_text, product_id, timestamp) "
            "FROM STDIN WITH (FORMAT csv, HEADER true);",
            f,
        )
    # copy_expert streams from STDIN rather than going through
    # LoggingCursor.execute(), so it isn't captured automatically — log the
    # equivalent statement by hand for the dashboard's Setup tab.
    log = getattr(cursor.connection, "sql_log", None)
    if log is not None:
        log.append(
            "COPY customer_feedback (customer_id, channel, feedback_text, product_id, timestamp) "
            f"FROM '{os.path.basename(CUSTOMER_FEEDBACK_CSV)}' WITH (FORMAT csv, HEADER true);"
        )
    print(f"Loaded customer_feedback from {os.path.basename(CUSTOMER_FEEDBACK_CSV)}.")


def _seed_initial_catalog_pdf():
    bucket = _bucket_name()
    client = _s3_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
        print(f"Created bucket: {bucket}")

    key = f"{CATALOGS_PREFIX}/{INITIAL_CATALOG_PDF}"
    try:
        client.head_object(Bucket=bucket, Key=key)
        print(f"{INITIAL_CATALOG_PDF} already uploaded, skipping.")
        return
    except ClientError:
        pass
    client.upload_file(os.path.join(DATA_DIR, INITIAL_CATALOG_PDF), bucket, key)
    print(f"Uploaded {INITIAL_CATALOG_PDF} -> s3://{bucket}/{key}")


def seed_feedback_table(args=None, sql_log=None):
    """Create customer_feedback (if missing) and load it from the bundled
    CSV — only on the first run; a second run is a no-op."""
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            _seed_feedback_table(cursor)
    conn.close()
    return sql_log


def inspect_feedback_table(args=None, sql_log=None):
    """Read-only: show customer_feedback's structure and a sample of rows."""
    conn = get_connection(sql_log=sql_log)
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.customer_feedback');")
            (table_exists,) = cursor.fetchone()
            if not table_exists:
                raise RuntimeError(
                    'customer_feedback table not found — run "Seed customer_feedback" first.'
                )

            cursor.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'customer_feedback' ORDER BY ordinal_position;"
            )
            columns = cursor.fetchall()
            print("customer_feedback columns:")
            for name, data_type in columns:
                print(f"  {name}: {data_type}")

            cursor.execute("SELECT id, channel, feedback_text, product_id FROM customer_feedback ORDER BY id LIMIT 5;")
            rows = cursor.fetchall()
            print(f"\nSample rows ({len(rows)} of the table):")
            for row in rows:
                print(f"  {row}")
    conn.close()
    return sql_log


def seed_catalog_pdf(args=None, sql_log=None):
    """Upload the initial catalog PDF to MinIO (creating the bucket first if
    needed) — only on the first run; a second run is a no-op."""
    _seed_initial_catalog_pdf()
    print(f"Catalog PDF ready to visualize: {INITIAL_CATALOG_PDF}")
    return sql_log


def upload_pdf(filename, file_obj):
    """Upload a single PDF (e.g. from the dashboard's Upload tab) into the
    catalogs bucket, where Background auto-processing will pick it up."""
    bucket = _bucket_name()
    key = f"{CATALOGS_PREFIX}/{filename}"
    _s3_client().upload_fileobj(file_obj, bucket, key)
    return key


def upload_sample_pdf():
    """Upload the bundled second catalog PDF straight from the container's
    data/ dir — a one-click way for the Upload tab to demonstrate
    auto-processing picking up a new file, no local PDF needed."""
    with open(os.path.join(DATA_DIR, SAMPLE_UPLOAD_PDF), "rb") as f:
        return upload_pdf(SAMPLE_UPLOAD_PDF, f)


def get_pdf_bytes(filename):
    """Fetch a PDF's raw bytes from the catalogs bucket, for the dashboard's
    inline "visualize" viewer."""
    bucket = _bucket_name()
    key = f"{CATALOGS_PREFIX}/{filename}"
    obj = _s3_client().get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()
