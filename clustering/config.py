import os

# Cosine similarity threshold for assigning a post to an existing cluster.
# Posts with similarity >= this value join the nearest cluster; below it, a new
# cluster is created. Default 0.75 balances recall (not splitting true paraphrases)
# against precision (not merging unrelated claims).
CLUSTER_SIMILARITY_THRESHOLD = float(
    os.environ.get("CLUSTER_SIMILARITY_THRESHOLD", "0.75")
)

# How many hours back to consider clusters "active" for matching
CLUSTER_ACTIVE_HOURS = int(os.environ.get("CLUSTER_ACTIVE_HOURS", "24"))

# Sentence-transformers model name
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Embedding dimension for all-MiniLM-L6-v2
EMBEDDING_DIM = 384

# Re-clustering job interval in seconds
RECLUSTER_INTERVAL_SECONDS = int(os.environ.get("RECLUSTER_INTERVAL_SECONDS", "600"))
