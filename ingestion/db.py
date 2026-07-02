import psycopg2
import psycopg2.extras
from ingestion.config import DATABASE_URL


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db(conn=None):
    """Create the posts table if it doesn't exist."""
    owned = conn is None
    if owned:
        conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    post_id     TEXT PRIMARY KEY,
                    author_did  TEXT NOT NULL,
                    text        TEXT NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL,
                    raw_json    JSONB NOT NULL,
                    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        conn.commit()
    finally:
        if owned:
            conn.close()


def insert_post(conn, post_id: str, author_did: str, text: str, created_at, raw_json: dict):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO posts (post_id, author_did, text, created_at, raw_json)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (post_id) DO NOTHING
            """,
            (post_id, author_did, text, created_at, psycopg2.extras.Json(raw_json)),
        )
    conn.commit()
