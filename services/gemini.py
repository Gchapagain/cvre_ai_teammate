"""Shared Gemini access for every service: the client, retries, quota handling and timing log.

Services catch GeminiError and decide what to tell the user. Nothing here saves data.
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors

PROJECT_ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)
KEY_PLACEHOLDER = "PASTE_KEY_HERE"

# Current stable Flash model per https://ai.google.dev/gemini-api/docs/models
# (checked 2026-10-12). Override with GEMINI_MODEL in .env if it changes.
DEFAULT_MODEL = "gemini-3.8-flash"

# Temporary Gemini errors (rate limited or server busy) that are worth another try.
RETRYABLE_CODES = {429, 500, 502, 503, 504}
MAX_TRIES = 3
RETRY_WAIT_SECONDS = 5  # wait 5s after the first failure, 10s after the second


class GeminiError(Exception):
    """Gemini could not give an answer. The message is safe to show to a user."""


class GeminiQuotaError(GeminiError):
    """The daily quota is used up, so trying again today will not help."""


class GeminiBusyError(GeminiError):
    """Gemini was busy or rate limited on every try."""


class RateLimited(GeminiError):
    """The app's own AI limit was reached, so nothing was sent (see services/ai_limits.py)."""


# Only tools/screenshots.py sets this. It points at a JSON file of canned replies so the screenshots
# can show AI features without spending real requests. The app shows a SIMULATED AI chip while it is set.
SIMULATED_ENV = "CBRE_SIMULATED_GEMINI"


def simulated():
    return bool(os.getenv(SIMULATED_ENV))


class _SimulatedClient:
    """Answers from the canned replies file: the first reply whose 'when' text is in the prompt."""

    def __init__(self, path):
        self.replies = json.loads(Path(path).read_text())
        self.models = self

    def generate_content(self, model=None, contents=None, config=None):
        from types import SimpleNamespace
        prompt = contents if isinstance(contents, str) else str(contents)
        for reply in self.replies:
            if reply["when"] in prompt:
                return SimpleNamespace(text=json.dumps(reply["reply"]), candidates=[], usage_metadata=None)
        raise GeminiError("No simulated reply matches this request.")


def get_client():
    """Build a Gemini client using the key in .env."""
    if simulated():
        return _SimulatedClient(os.environ[SIMULATED_ENV])
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == KEY_PLACEHOLDER:
        raise GeminiError("GEMINI_API_KEY is not set. Put your real key in the .env file.")
    return genai.Client(api_key=api_key)


def model_name(model=None):
    return model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def _token_note(response):
    """Describe token usage for the timing log, if the response reports it."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return ""
    return (f" (prompt {usage.prompt_token_count} tokens, "
            f"thinking {usage.thoughts_token_count or 0}, output {usage.candidates_token_count})")


def _is_daily_quota(exc):
    """True when a 429 is the per-day quota, which waiting a few seconds cannot fix."""
    return exc.code == 429 and "PerDay" in str(exc.details)


def _daily_quota_message(exc):
    wait = re.search(r"retry in ((?:\d+h)?(?:\d+m)?)", exc.message or "")
    when = f" Google says it resets in about {wait.group(1)}." if wait and wait.group(1) else ""
    return f"Gemini daily quota is used up, so trying again now will not help.{when}"


def generate(client, contents, config, model=None):
    """Ask Gemini once and return the reply text. See generate_response."""
    return generate_response(client, contents, config, model).text


def generate_response(client, contents, config, model=None):
    """Ask Gemini once and return the whole response, retrying temporary errors up to MAX_TRIES times.

    The whole response is needed when its metadata matters (for example the sources behind a
    web-search answer). A used-up daily quota stops straight away instead of retrying.
    The app's own rate limits are checked first; if one is reached, RateLimited is raised and nothing is sent.
    """
    from services import ai_limits
    ai_limits.acquire()
    started = time.perf_counter()
    for attempt in range(1, MAX_TRIES + 1):
        attempt_started = time.perf_counter()
        try:
            response = client.models.generate_content(model=model_name(model), contents=contents, config=config)
        except errors.APIError as exc:
            log.info("Gemini attempt %d/%d: failed with %s %s after %.1fs",
                     attempt, MAX_TRIES, exc.code, exc.status, time.perf_counter() - attempt_started)
            if _is_daily_quota(exc):
                raise GeminiQuotaError(_daily_quota_message(exc)) from exc
            if exc.code not in RETRYABLE_CODES:
                raise GeminiError(f"Gemini rejected the request ({exc.code} {exc.status}): {exc.message}") from exc
            last_error = exc
            if attempt < MAX_TRIES:
                time.sleep(RETRY_WAIT_SECONDS * attempt)
        else:
            log.info("Gemini attempt %d/%d: ok in %.1fs%s",
                     attempt, MAX_TRIES, time.perf_counter() - attempt_started, _token_note(response))
            log.info("Gemini total: %.1fs over %d attempt(s)", time.perf_counter() - started, attempt)
            if not response.text:
                raise GeminiError("Gemini returned an empty response.")
            return response
    log.info("Gemini total: %.1fs over %d attempt(s), all failed", time.perf_counter() - started, MAX_TRIES)
    raise GeminiBusyError(
        f"Gemini was unavailable after {MAX_TRIES} tries "
        f"(last error: {last_error.code} {last_error.status}). Please try again in a few minutes."
    ) from last_error


def _fingerprint(prompt):
    return hashlib.sha256(prompt.encode()).hexdigest()


def save_recording(path, prompt, response_text, model=None):
    """Save a real Gemini reply to a file so it can be replayed without calling the API."""
    recording = {
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "model": model_name(model),
        "prompt_sha256": _fingerprint(prompt),
        "response_text": response_text,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recording, indent=2))


def load_recording(path, prompt):
    """Return the recorded reply, refusing one that was made for a different prompt."""
    path = Path(path)
    if not path.exists():
        raise GeminiError(f"No recorded Gemini response at {path}. Record one with a live run first.")
    recording = json.loads(path.read_text())
    if recording.get("prompt_sha256") != _fingerprint(prompt):
        raise GeminiError(f"The recording at {path} is out of date: the prompt or the data has changed since it was made.")
    return recording["response_text"]
