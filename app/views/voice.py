"""Record or upload audio, have the AI transcribe it, and let the person check the words.

The audio is never saved: it is sent to Gemini once, when Transcribe is pressed, and only
the transcript the person has checked is used or stored.
"""

import logging

import streamlit as st

from services import deals, gemini, transcribe

log = logging.getLogger(__name__)

NOTICE = "Audio is sent to Gemini for transcription and is not saved."
MIC_HELP = ("If the microphone is blocked, allow it for this site in your browser's settings, "
            "or upload a file instead. Each transcription uses one AI request.")
TRANSCRIPT_LABEL = "AI transcript - please check it"
MAX_UPLOAD_MB = transcribe.MAX_AUDIO_BYTES // 1024 // 1024  # what the upload box itself allows
QUOTA_MESSAGE = "The AI's daily quota is used up, so this can't be transcribed right now. {detail} You can type instead."
BUSY_MESSAGE = "The AI is busy or rate-limited at the moment. Try again in a minute, or type instead."
OTHER_MESSAGE = "The recording could not be transcribed just now. {detail} You can type instead."


def _state(key):
    return st.session_state.setdefault(f"voice_{key}", {"round": 0, "transcript": None, "message": None})


def _transcribe(state, audio, from_microphone):
    """Send the audio once and keep the words or a friendly message. Never raises."""
    state["transcript"], state["message"] = None, None
    try:
        # The browser recorder always produces WAV; an uploaded file is judged by its name.
        mime_type = "audio/wav" if from_microphone else transcribe.mime_type_for(audio.name)
        state["transcript"] = transcribe.transcribe(audio.getvalue(), mime_type)
    except transcribe.TranscriptionError as exc:
        state["message"] = str(exc)
    except gemini.GeminiQuotaError as exc:
        state["message"] = QUOTA_MESSAGE.format(detail=exc)
    except gemini.GeminiBusyError:
        state["message"] = BUSY_MESSAGE
    except gemini.GeminiError as exc:
        state["message"] = OTHER_MESSAGE.format(detail=exc)
    except Exception:
        log.exception("Transcription failed")
        state["message"] = OTHER_MESSAGE.format(detail="Something unexpected went wrong.")


def _reset(state):
    """Clear the recorder so the same audio cannot be sent or used twice."""
    state.update(round=state["round"] + 1, transcript=None, message=None)


def render(key, deal_id=None, use_label="Use as my message"):
    """Draw the recorder. Returns the checked text when the person presses the use button, else None."""
    state = _state(key)
    # Text the person chose to use on the previous run. Handing it over now, after a fresh
    # run, means the recorder below is already cleared.
    used = state.pop("pending", None)
    with st.expander(":material/mic: Record or upload audio", key=f"{key}_voice"):
        st.caption(NOTICE)
        recording = st.audio_input("Record with the microphone", key=f"{key}_mic_{state['round']}")
        upload = st.file_uploader("Or upload an audio file (mp3, m4a, wav)", type=["mp3", "m4a", "wav"],
                                  max_upload_size=MAX_UPLOAD_MB,
                                  key=f"{key}_audio_{state['round']}")
        st.caption(MIC_HELP)
        audio = recording or upload
        if st.button("Transcribe", key=f"{key}_transcribe", icon=":material/graphic_eq:", disabled=audio is None):
            with st.spinner("Transcribing..."):
                _transcribe(state, audio, from_microphone=recording is not None)
        if state["message"]:
            st.warning(state["message"])
        if state["transcript"] is not None:
            text = st.text_area(TRANSCRIPT_LABEL, value=state["transcript"], key=f"{key}_text_{state['round']}")
            buttons = st.container(horizontal=True)
            if buttons.button(use_label, key=f"{key}_use", type="primary", disabled=not text.strip()):
                state["pending"] = text.strip()
                _reset(state)
                st.rerun()
            if deal_id is not None and buttons.button("Save as a note on this deal", key=f"{key}_save_note",
                                                       disabled=not text.strip()):
                deals.add_note(deal_id, text, "Recording")
                _reset(state)
                state["message"] = "Saved as a note on this deal. See Notes on the Review tab."
                st.rerun()
    return used
