"""The deal chat, used by the Ask AI tab and the floating assistant. Gemini is only called when a message is sent."""

import logging

import streamlit as st

from app import style
from app.views import voice
from services import gemini, qa

log = logging.getLogger(__name__)

LABEL_NO_ANSWER = "No answer"
PILL_KINDS = {qa.LABEL_FROM_DEAL: "from-deal", qa.LABEL_FROM_DEALS: "from-deal",
              qa.LABEL_NOT_VERIFIED: "not-verified", LABEL_NO_ANSWER: "no-answer"}

QUOTA_MESSAGE = ("I can't answer right now because the AI's daily quota is used up. {detail} "
                 "Your question was not answered and nothing was changed.")
BUSY_MESSAGE = ("The AI is busy or rate-limited at the moment, so I couldn't answer. "
                "Please try again in a minute. Nothing was changed.")
OTHER_MESSAGE = "I couldn't get an answer from the AI just now. {detail} Nothing was changed."


def _notice(text):
    return {"role": "assistant", "text": text, "label": LABEL_NO_ANSWER, "sources": [], "note": "", "deals": []}


def get_answer(deal_id, question, messages):
    """Ask the Q&A service and return a chat message. deal_id None means all deals.

    Never raises: problems become a friendly notice.
    """
    history = [{"role": m["role"], "text": m["text"]} for m in messages if m.get("label") != LABEL_NO_ANSWER]
    try:
        answer = qa.ask_all(question, history) if deal_id is None else qa.ask(deal_id, question, history)
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
            "sources": answer.sources, "note": answer.note, "deals": answer.deals}


def _show(message):
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            style.html(style.pill(message["label"], PILL_KINDS[message["label"]]))
        st.markdown(message["text"].replace("$", "\\$"))  # a bare $ would start maths formatting
        if message.get("deals"):
            st.caption("Deals used: " + ", ".join(message["deals"]))
        if message.get("sources"):
            st.caption("Source: " + ", ".join(message["sources"]))
        if message.get("note"):
            st.caption(message["note"])


def chat_key(deal_id):
    """Where a chat's messages live in the session. The tab and the assistant share one chat per deal."""
    return "chat_all" if deal_id is None else f"chat_{deal_id}"


def render_chat(deal_id, prefix=""):
    """The chat for one deal, or for all deals when deal_id is None."""
    messages = st.session_state.setdefault(chat_key(deal_id), [])
    scope = "all" if deal_id is None else deal_id
    st.toggle("Web search", value=False, disabled=True, key=f"{prefix}web_search_{scope}")
    st.caption("Web search: coming in a later step.")

    history = st.container()
    question = st.chat_input("Ask about all deals" if deal_id is None else "Ask about this deal",
                             key=f"{prefix}chat_input_{scope}")
    # A checked transcript is sent exactly like a typed message.
    question = question or voice.render(f"{prefix}chat_{scope}", deal_id=deal_id)
    if question:
        with st.spinner("Reading the deal data..."):
            reply = get_answer(deal_id, question, messages)
        messages.append({"role": "user", "text": question})
        messages.append(reply)
    with history:
        if not messages:
            st.info("No messages yet. Try: What is the total annual rent?" if deal_id is not None
                    else "No messages yet. Try: Which deals have anomalies?")
        for message in messages:
            _show(message)


def render(deal):
    st.caption("Answers come only from this deal's saved data: rent roll, T-12, flags and documents. "
               "Every answer is labelled. The AI is only contacted when you send a message.")
    render_chat(deal["id"])
