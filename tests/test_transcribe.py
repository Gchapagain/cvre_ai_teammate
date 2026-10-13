"""Tests for transcription. Gemini is always simulated; no audio is ever sent anywhere real."""

import unittest
from types import SimpleNamespace
from unittest import mock

from services import gemini, transcribe
from tests.test_extraction import daily_quota_error, gemini_error

AUDIO = b"RIFF" + b"\x00" * 4000  # made-up bytes standing in for a short recording


def fake_gemini(reply, calls=None):
    def generate_content(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


class TestTranscribe(unittest.TestCase):
    def test_returns_the_words_gemini_heard(self):
        text = transcribe.transcribe(AUDIO, client=fake_gemini("  A 40,000 square foot warehouse in Fort Worth.  "))
        self.assertEqual(text, "A 40,000 square foot warehouse in Fort Worth.")

    def test_sends_the_audio_and_a_word_for_word_instruction_in_one_request(self):
        calls = []
        transcribe.transcribe(AUDIO, "audio/mp3", client=fake_gemini("Hello.", calls))
        self.assertEqual(len(calls), 1)
        audio_part, prompt = calls[0]["contents"]
        self.assertEqual(audio_part.inline_data.data, AUDIO)
        self.assertEqual(audio_part.inline_data.mime_type, "audio/mp3")
        self.assertIn("word for word", prompt)
        self.assertIn("Do not summarise", prompt)

    def test_empty_recording_is_rejected_before_anything_is_sent(self):
        calls = []
        for data in (b"", None, b"RIFF" + b"\x00" * 40):
            with self.assertRaises(transcribe.TranscriptionError) as caught:
                transcribe.transcribe(data, client=fake_gemini("x", calls))
            self.assertIn("empty", str(caught.exception))
        self.assertEqual(calls, [])

    def test_file_that_is_too_large_is_rejected_before_anything_is_sent(self):
        calls = []
        with self.assertRaises(transcribe.TranscriptionError) as caught:
            transcribe.transcribe(b"\x00" * (transcribe.MAX_AUDIO_BYTES + 1), client=fake_gemini("x", calls))
        self.assertIn("too large", str(caught.exception))
        self.assertIn("15 MB", str(caught.exception))
        self.assertEqual(calls, [])

    def test_a_file_exactly_at_the_limit_is_accepted(self):
        self.assertEqual(transcribe.transcribe(b"\x01" * transcribe.MAX_AUDIO_BYTES, client=fake_gemini("Fine.")), "Fine.")

    def test_no_speech_is_a_friendly_error_not_a_transcript(self):
        for reply in ("NO_SPEECH", "  NO_SPEECH\n"):
            with self.assertRaises(transcribe.TranscriptionError) as caught:
                transcribe.transcribe(AUDIO, client=fake_gemini(reply))
            self.assertIn("No speech", str(caught.exception))

    def test_quota_and_busy_errors_pass_through(self):
        with mock.patch.object(gemini.time, "sleep"):
            with self.assertRaises(gemini.GeminiQuotaError):
                transcribe.transcribe(AUDIO, client=fake_gemini(daily_quota_error()))
            calls = []
            with self.assertRaises(gemini.GeminiBusyError):
                transcribe.transcribe(AUDIO, client=fake_gemini(gemini_error(503, "UNAVAILABLE"), calls))
            self.assertEqual(len(calls), 3)

    def test_file_types(self):
        self.assertEqual(transcribe.mime_type_for("memo.MP3"), "audio/mp3")
        self.assertEqual(transcribe.mime_type_for("memo.m4a"), "audio/m4a")
        self.assertEqual(transcribe.mime_type_for("memo.wav"), "audio/wav")
        for name in ("memo.ogg", "memo.txt", "memo", "", None):
            with self.assertRaises(transcribe.TranscriptionError):
                transcribe.mime_type_for(name)

    def test_the_module_never_writes_a_file(self):
        with mock.patch("builtins.open", side_effect=AssertionError("audio must not be written to disk")):
            transcribe.transcribe(AUDIO, client=fake_gemini("Hello."))


if __name__ == "__main__":
    unittest.main()
