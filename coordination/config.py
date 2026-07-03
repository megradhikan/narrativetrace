import os

# Time window within which multiple accounts posting the same claim triggers a signal (seconds)
TIMING_WINDOW_SECONDS = int(os.environ.get("TIMING_WINDOW_SECONDS", "120"))

# Minimum number of distinct accounts posting within the window to trigger
MIN_ACCOUNTS_IN_WINDOW = int(os.environ.get("MIN_ACCOUNTS_IN_WINDOW", "3"))

# Cosine similarity threshold to consider two posts "near-identical" for timing check
NEAR_IDENTICAL_THRESHOLD = float(os.environ.get("NEAR_IDENTICAL_THRESHOLD", "0.92"))

# How often the coordination detector runs (seconds)
DETECTION_INTERVAL_SECONDS = int(os.environ.get("DETECTION_INTERVAL_SECONDS", "60"))

# How far back to look at posts when running detection (hours)
DETECTION_LOOKBACK_HOURS = int(os.environ.get("DETECTION_LOOKBACK_HOURS", "24"))
