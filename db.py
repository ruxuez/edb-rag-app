import os
import re
import psycopg2
import psycopg2.extensions
from urllib.parse import urlparse, urlunparse

# Redact credential values before they're ever logged/displayed — several
# statements in this app embed API keys / access keys inline as JSON
# (aidb.create_model, pgfs.create_storage_location).
_SECRET_KEY_PATTERN = re.compile(
    r'"(api_key|access_key_id|secret_access_key|password|session_token)"\s*:\s*"[^"]*"',
    re.IGNORECASE,
)


def _redact(sql_text):
    return _SECRET_KEY_PATTERN.sub(r'"\1": "***REDACTED***"', sql_text)


class LoggingConnection(psycopg2.extensions.connection):
    """Connection subclass with a real (Python-level) attribute slot for the
    SQL log — plain psycopg2 connections don't support arbitrary attribute
    assignment, since they're a C extension type."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_log = []


class LoggingCursor(psycopg2.extensions.cursor):
    """Cursor that appends every statement it runs (fully interpolated, via
    psycopg2's own .query) to connection.sql_log, so the dashboard's Setup
    tab can show the real SQL behind each step."""

    def execute(self, query, vars=None):
        try:
            return super().execute(query, vars)
        finally:
            log = getattr(self.connection, "sql_log", None)
            if log is not None and self.query is not None:
                q = self.query
                q = q.decode() if isinstance(q, bytes) else q
                log.append(_redact(q))


def get_connection(dbname=None, sql_log=None):
    uri = os.getenv("DATABASE_URL")
    if dbname:
        parsed = urlparse(uri)
        parsed = parsed._replace(path=f"/{dbname}")
        uri = urlunparse(parsed)

    conn = psycopg2.connect(uri, connection_factory=LoggingConnection, cursor_factory=LoggingCursor)
    if sql_log is not None:
        # Share the caller's list (in place) rather than the fresh one
        # LoggingConnection.__init__ created, so callers who pass one keep
        # accumulating into it across multiple get_connection() calls.
        conn.sql_log = sql_log

    return conn
