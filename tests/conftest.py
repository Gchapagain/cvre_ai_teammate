"""Shared test settings.

The app's AI rate limits (services/ai_limits.py) would stop the screen tests, which send several
simulated AI requests in a row. They are switched off here; tests/test_ai_limits.py sets its own.
"""

import os
import tempfile
from pathlib import Path

# Tests never open the real local database (cbre_ai_teammate.db). Each test points the app at its own
# throwaway database; this default catches anything that forgets, even a db module loaded afresh mid-run
# (app/fresh.py can do that), because db.DB_PATH is read from this setting on import.
os.environ["CBRE_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="cbre-tests-")) / "not-the-real-database.db")

os.environ.setdefault("AI_DAILY_LIMIT", "100000")
os.environ.setdefault("AI_SESSION_HOURLY_LIMIT", "100000")

# The OM autopilot calls Gemini and web search on its own in the running app; never in tests. The setting is
# also switched off in code, because some tests replace the whole environment (tests/test_connections.with_keys).
os.environ["OM_AUTOPILOT"] = "off"

from services import om_autopilot  # noqa: E402

om_autopilot.switch_off()
