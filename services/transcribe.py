"""Turn a short recording into text with Gemini.

The audio is held in memory only for the request. Nothing in this module writes it to
disk or to the database; only the transcript a person has checked is ever saved, elsewhere.
"""

from pathlib import Path

from google.genai import types

from services import gemini

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # Gemini takes about 20 MB per request in total; leave room
MIN_AUDIO_BYTES = 2000              # less than this is a header with no sound in it
MIME_TYPES = {".wav": "audio/wav", ".mp3": "audio/mp3", ".m4a": "audio/m4a"}
NO_SPEECH = "NO_SPEECH"

PROMPT = f"""Transcribe this recording word for word.

Rules:
- Write only what is said. Do not summarise, tidy up, translate or add anything.
- Write numbers and names as spoken. If a word is unclear, write [unclear].
- If there is no speech, reply with exactly: {NO_SPEECH}
"""


class TranscriptionError(Exception):
    """The recording cannot be transcribed. The message is safe to show to a user."""


def mime_type_for(filename):
    """The audio type for a file name, or a clear error if it is not one we accept."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in MIME_TYPES:
        raise TranscriptionError("That file type is not supported. Use an mp3, m4a or wav file.")
    return MIME_TYPES[suffix]


def check_audio(data):
    """Reject recordings that are empty or too large before anything is sent."""
    if not data or len(data) < MIN_AUDIO_BYTES:
        raise TranscriptionError("The recording is empty. Record again, or check the microphone is allowed.")
    if len(data) > MAX_AUDIO_BYTES:
        size, limit = len(data) / 1024 / 1024, MAX_AUDIO_BYTES // 1024 // 1024
        raise TranscriptionError(f"The recording is too large ({size:.0f} MB). The limit is {limit} MB, a few minutes of speech.")


def transcribe(data, mime_type="audio/wav", client=None, model=None):
    """Return the words in the recording. Uses one Gemini request.

    Raises TranscriptionError for a bad recording and gemini.GeminiError if Gemini cannot be reached.
    """
    check_audio(data)
    contents = [types.Part.from_bytes(data=data, mime_type=mime_type), PROMPT]
    text = gemini.generate(client or gemini.get_client(), contents,
                           types.GenerateContentConfig(temperature=0), model).strip()
    if not text or text == NO_SPEECH:
        raise TranscriptionError("No speech was heard in the recording. Try again a little closer to the microphone.")
    return text
