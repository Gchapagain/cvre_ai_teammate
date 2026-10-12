"""Ask AI tab: a chat about one deal. Gemini is only called when a message is sent."""

import logging

import streamlit as st

from app import style
from services import gemini, qa

log = logging.getLogger(__name__)

LABEL_NO_ANSWER = "No answer"
PILL_KINDS = {qa.LABEL_FROM_DEAL: "from-deal", qa.LABEL_NOT_VERIFIED: "not-verified", LABEL_NO_ANSWER: "no-answer"}

QUOTA_MESSAGE = ("I can't answer right now because the AI's daily quota is used up. {detail} "
                 "Your question was not answered and nothing was changed.")
BUSY_MESSAGE = ("The AI is busy or rate-limited at the moment, so I couldn't answer. "
                "Please try again in a minute. Nothing was changed.")
OTHER_MESSAGE = "I couldn't get an answer from the AI just now. {detail} Nothing was changed."


def _notice(text):
    return {"role": "assistant", "text": text, "label": LABEL_NO_ANSWER, "sources": [], "note": ""}


def get_answer(deal_id, question, messages):
    """Ask the Q&A service and return a chat message. Never raises: problems become a friendly notice."""
    history = [{"role": m["role"], "text": m["text"]} for m in messages if m.get("label") != LABEL_NO_ANSWER]
    try:
        answer = qa.ask(deal_id, question, history)
    except gemini.GeminiQuotaError as exc:
        return _notice(QUOTA_MESSAGE.format(detail=exc))
    except gemini.GeminiBusyError:
        return _notice(BUSY_MESSAGE)
    except gemini.GeminiError as exc:
        return _notice(OTHER_MESSAGE.format(detail=exc))
    except Exception:
        log.exception("Ask AI failed")
        return _notice(OTHER_MESSAGE.format(detail="Something unexpected went wrong."))
    return {"role": "assistant", "text": answer.text, "label": answer.label,
            "sources": answer.sources, "note": answer.note}


def _show(message):
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            style.html(style.pill(message["label"], PILL_KINDS[message["label"]]))
        st.markdown(message["text"].replace("$", "\\$"))  # a bare $ would start maths formatting
        if message.get("sources"):
            st.caption("Source: " + ", ".join(message["sources"]))
        if message.get("note"):
            st.caption(message["note"])


def render(deal):
    messages = st.session_state.setdefault(f"chat_{deal['id']}", [])
    st.caption("Answers come only from this deal's saved data: rent roll, T-12, flags and documents. "
               "Every answer is labelled. The AI is only contacted when you send a message.")
    st.toggle("Web search", value=False, disabled=True, key=f"web_search_{deal['id']}")
    st.caption("Web search: coming in a later step.")

    history = st.container()
    question = st.chat_input("Ask about this deal", key=f"chat_input_{deal['id']}")
    if question:
        with st.spinner("Reading this deal's data..."):
            reply = get_answer(deal["id"], question, messages)
        messages.append({"role": "user", "text": question})
        messages.append(reply)
    with history:
        if not messages:
            st.info("No messages yet. Try: What is the total annual rent?")
        for message in messages:
            _show(message)
