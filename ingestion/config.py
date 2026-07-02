import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://localhost:5432/narrativetrace",
)

FIREHOSE_HOST = os.environ.get("FIREHOSE_HOST", "bsky.network")

RECONNECT_BASE_DELAY = float(os.environ.get("RECONNECT_BASE_DELAY", "1"))
RECONNECT_MAX_DELAY = float(os.environ.get("RECONNECT_MAX_DELAY", "60"))
