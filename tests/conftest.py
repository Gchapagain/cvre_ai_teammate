"""Shared test settings.

The app's AI rate limits (services/ai_limits.py) would stop the screen tests, which send several
simulated AI requests in a row. They are switched off here; tests/test_ai_limits.py sets its own.
"""

import os

os.environ.setdefault("AI_DAILY_LIMIT", "100000")
os.environ.setdefault("AI_SESSION_HOURLY_LIMIT", "100000")
