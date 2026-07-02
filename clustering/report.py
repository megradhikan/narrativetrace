"""
Simple CLI cluster report: python -m clustering.report

Prints active clusters sorted by post count.
"""

import logging
from ingestion.db import get_connection
from clustering.config import CLUSTER_ACTIVE_HOURS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def main():
    conn = get_connection()
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT c.cluster_id, c.post_count, c.updated_at,
                       (SELECT p.text FROM posts p
                        JOIN cluster_posts cp2 ON cp2.post_id = p.post_id
                        WHERE cp2.cluster_id = c.cluster_id
                        ORDER BY p.created_at ASC LIMIT 1) AS sample_text
                FROM clusters c
                WHERE c.updated_at > NOW() - INTERVAL '%s hours'
                ORDER BY c.post_count DESC
                LIMIT 50
            """, (CLUSTER_ACTIVE_HOURS,))
            rows = cur.fetchall()

        print(f"\n{'─'*80}")
        print(f"{'CLUSTER ID':<38} {'POSTS':>6}  SAMPLE TEXT")
        print(f"{'─'*80}")
        for row in rows:
            sample = (row["sample_text"] or "")[:60].replace("\n", " ")
            print(f"{row['cluster_id']:<38} {row['post_count']:>6}  {sample}")
        print(f"{'─'*80}")
        print(f"Total active clusters: {len(rows)}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
