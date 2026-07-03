"""
FastAPI backend — v0.3 REST endpoints (polling, no WebSocket yet).

Run with:  uvicorn backend.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

import asyncio
import json

import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ingestion.db import get_connection, init_db
from clustering.db import init_cluster_tables
from clustering.classify_job import init_topic_columns, start_background as start_classify
from graph.db import init_graph_tables, get_edges_for_cluster
from graph.builder import load_cluster_graph, graph_to_dict

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection()
    init_db(conn)
    init_cluster_tables(conn)
    init_topic_columns(conn)
    init_graph_tables(conn)
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


@app.get("/stats")
def get_stats():
    """Live stats: total posts ingested, active clusters, posts in last minute."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS total FROM posts")
            total_posts = cur.fetchone()["total"]
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM clusters
                WHERE updated_at > NOW() - INTERVAL '24 hours'
            """)
            active_clusters = cur.fetchone()["cnt"]
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM posts
                WHERE ingested_at > NOW() - INTERVAL '1 minute'
            """)
            posts_last_minute = cur.fetchone()["cnt"]
        return {
            "total_posts": total_posts,
            "active_clusters": active_clusters,
            "posts_last_minute": posts_last_minute,
            "firehose_status": "connected",
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# WebSocket: push cluster updates to connected frontends
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self._cluster_subs: dict[str, list[WebSocket]] = {}
        self._global_subs: list[WebSocket] = []

    async def connect_global(self, ws: WebSocket):
        await ws.accept()
        self._global_subs.append(ws)

    async def connect_cluster(self, ws: WebSocket, cluster_id: str):
        await ws.accept()
        self._cluster_subs.setdefault(cluster_id, []).append(ws)

    def disconnect_global(self, ws: WebSocket):
        self._global_subs.discard(ws) if hasattr(self._global_subs, "discard") else None
        try:
            self._global_subs.remove(ws)
        except ValueError:
            pass

    def disconnect_cluster(self, ws: WebSocket, cluster_id: str):
        subs = self._cluster_subs.get(cluster_id, [])
        try:
            subs.remove(ws)
        except ValueError:
            pass

    async def broadcast_cluster_update(self, cluster_id: str, data: dict):
        msg = json.dumps({"type": "cluster_update", "cluster_id": cluster_id, **data})
        for ws in list(self._global_subs):
            try:
                await ws.send_text(msg)
            except Exception:
                self.disconnect_global(ws)
        for ws in list(self._cluster_subs.get(cluster_id, [])):
            try:
                await ws.send_text(msg)
            except Exception:
                self.disconnect_cluster(ws, cluster_id)

    async def broadcast_graph_edge(self, cluster_id: str, edge: dict):
        msg = json.dumps({"type": "graph_edge", "cluster_id": cluster_id, "edge": edge})
        for ws in list(self._cluster_subs.get(cluster_id, [])):
            try:
                await ws.send_text(msg)
            except Exception:
                self.disconnect_cluster(ws, cluster_id)


manager = ConnectionManager()


@app.websocket("/ws/clusters")
async def ws_clusters(websocket: WebSocket):
    """Global WebSocket: pushes cluster list updates every 3 seconds."""
    await manager.connect_global(websocket)
    try:
        while True:
            conn = get_connection()
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT c.cluster_id, c.post_count, c.topic, c.topic_score,
                               c.updated_at::text,
                               (SELECT p.text FROM posts p
                                JOIN cluster_posts cp2 ON cp2.post_id = p.post_id
                                WHERE cp2.cluster_id = c.cluster_id
                                ORDER BY p.created_at ASC LIMIT 1) AS sample_text
                        FROM clusters c
                        WHERE c.updated_at > NOW() - INTERVAL '24 hours'
                        ORDER BY c.post_count DESC LIMIT 50
                    """)
                    clusters = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()
            await websocket.send_text(json.dumps({
                "type": "clusters_snapshot",
                "clusters": clusters,
            }))
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        manager.disconnect_global(websocket)


@app.websocket("/ws/clusters/{cluster_id}/graph")
async def ws_cluster_graph(websocket: WebSocket, cluster_id: str):
    """Cluster-specific WebSocket: sends full graph then streams new edges."""
    await manager.connect_cluster(websocket, cluster_id)
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT cluster_id FROM clusters WHERE cluster_id = %s", (cluster_id,))
                if not cur.fetchone():
                    await websocket.send_text(json.dumps({"type": "error", "detail": "Cluster not found"}))
                    await websocket.close(code=1008)
                    return
            G = load_cluster_graph(conn, cluster_id)
        finally:
            conn.close()
        await websocket.send_text(json.dumps({
            "type": "graph_snapshot",
            "cluster_id": cluster_id,
            **graph_to_dict(G),
        }))
        # Keep alive — new edges are pushed via manager.broadcast_graph_edge
        while True:
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        manager.disconnect_cluster(websocket, cluster_id)


@app.get("/clusters/{cluster_id}/graph")
def get_cluster_graph(cluster_id: str):
    """Return the interaction graph for a cluster as nodes + links."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT cluster_id FROM clusters WHERE cluster_id = %s", (cluster_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Cluster not found")
        G = load_cluster_graph(conn, cluster_id)
        return graph_to_dict(G)
    finally:
        conn.close()


@app.get("/health")
def health():
    return {"status": "ok"}
