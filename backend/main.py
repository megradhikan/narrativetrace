"""
FastAPI backend — v0.3 REST endpoints (polling, no WebSocket yet).

Run with:  uvicorn backend.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ingestion.db import get_connection, init_db
from clustering.db import init_cluster_tables
from clustering.classify_job import init_topic_columns, start_background as start_classify

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection()
    init_db(conn)
    init_cluster_tables(conn)
    init_topic_columns(conn)
    conn.close()
    start_classify()
    yield


app = FastAPI(title="NarrativeTrace API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ClusterSummary(BaseModel):
    cluster_id: str
    post_count: int
    topic: Optional[str]
    topic_score: Optional[float]
    updated_at: str
    sample_text: Optional[str]


class ClusterDetail(ClusterSummary):
    posts: list[dict]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/clusters", response_model=list[ClusterSummary])
def list_clusters(
    topic: Optional[str] = Query(None, description="Filter by topic label"),
    limit: int = Query(50, le=200),
):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            base_q = """
                SELECT
                    c.cluster_id,
                    c.post_count,
                    c.topic,
                    c.topic_score,
                    c.updated_at::text AS updated_at,
                    (
                        SELECT p.text FROM posts p
                        JOIN cluster_posts cp2 ON cp2.post_id = p.post_id
                        WHERE cp2.cluster_id = c.cluster_id
                        ORDER BY p.created_at ASC LIMIT 1
                    ) AS sample_text
                FROM clusters c
                WHERE c.updated_at > NOW() - INTERVAL '24 hours'
            """
            params: list = []
            if topic:
                base_q += " AND c.topic = %s"
                params.append(topic)
            base_q += " ORDER BY c.post_count DESC LIMIT %s"
            params.append(limit)
            cur.execute(base_q, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/clusters/{cluster_id}", response_model=ClusterDetail)
def get_cluster(cluster_id: str):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT c.cluster_id, c.post_count, c.topic, c.topic_score,
                       c.updated_at::text AS updated_at
                FROM clusters c WHERE c.cluster_id = %s
            """, (cluster_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Cluster not found")

            cur.execute("""
                SELECT p.post_id, p.author_did, p.text, p.created_at::text AS created_at
                FROM posts p
                JOIN cluster_posts cp ON cp.post_id = p.post_id
                WHERE cp.cluster_id = %s
                ORDER BY p.created_at DESC
                LIMIT 100
            """, (cluster_id,))
            posts = [dict(r) for r in cur.fetchall()]

        result = dict(row)
        result["posts"] = posts
        result["sample_text"] = posts[0]["text"] if posts else None
        return result
    finally:
        conn.close()


@app.get("/topics")
def list_topics():
    """Return available topic labels and their cluster counts."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT topic, count(*) AS cluster_count
                FROM clusters
                WHERE topic IS NOT NULL
                  AND updated_at > NOW() - INTERVAL '24 hours'
                GROUP BY topic
                ORDER BY cluster_count DESC
            """)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.get("/health")
def health():
    return {"status": "ok"}
