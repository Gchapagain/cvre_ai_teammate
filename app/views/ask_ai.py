"""The deal chat, used by the Ask AI tab and the floating assistant. Gemini is only called when a message is sent."""

import logging

import streamlit as st

from app import style
from app.views import voice
from services import ai_limits, gemini, qa

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
    except gemini.RateLimited as exc:  # our own limit, not Google's
        return _notice(f"{exc} Nothing was changed.")
    except gemini.GeminiError as exc:
        return _notice(OTHER_MESSAGE.format(detail=exc))
    except Exception:
        log.exception("Ask AI failed")
        return _notice(OTHER_MESSAGE.format(detail="Something unexpected went wrong."))
    return {"role": "assistant", "text": answer.text, "label": answer.label,
            "sources": answer.sources, "note": answer.note, "deals": answer.deals}


# ---------- the chat card (one component, used by the Ask AI tab and the floating AI Teammate dialog) ----------

SUGGESTIONS = {"deal": ["What is the total annual rent?", "Which units are flagged and why?", "When do the leases end?"],
               "all": ["Which deals have anomalies?", "Which deal is closest to done?", "Compare the total SF of each deal"]}
WELCOME = {"deal": "Hi, I'm your AI Teammate. I answer only from this deal's saved data and label every answer. "
                   "I never send anything to anyone.",
           "all": "Hi, I'm your AI Teammate. I answer only from the deals saved here, name the deals I used and label "
                  "every answer. I never send anything to anyone."}
TYPING = '<div class="chat-typing" aria-label="The AI Teammate is answering"><span></span><span></span><span></span></div>'


def bubble_kind(message):
    """'user' (right, gold), 'ai' (left, sage) or 'notice' (left, soft amber: limits, quota and errors)."""
    if message["role"] == "user":
        return "user"
    return "notice" if message.get("label") == LABEL_NO_ANSWER else "ai"


def _show(message, key):
    """One message as a bubble. AI answers keep their label and their sources inside the bubble."""
    with st.container(key=f"{key}_{bubble_kind(message)}"):
        if message["role"] == "assistant" and message.get("label"):  # every answer is labelled; the greeting is not an answer
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


def _ask_suggestion(pending_key, question):
    st.session_state[pending_key] = question


def _scroll_to_newest(body_key):
    """Keep the message area at the newest message after each answer."""
    st.html(f"""<script>
    setTimeout(function () {{
      const doc = window.parent.document || document;
      doc.querySelectorAll('.st-key-{body_key}').forEach(function (box) {{ box.scrollTop = box.scrollHeight; }});
    }}, 150);
    </script>""", unsafe_allow_javascript=True)


def render_chat(deal_id, prefix="", header=True):
    """The chat card for one deal, or all deals when deal_id is None.

    header: draw the forest title bar (the tab). The dialog has its own title bar, styled the same.
    Gemini is called only when a message is sent or a suggestion is clicked (1 request each).
    """
    messages = st.session_state.setdefault(chat_key(deal_id), [])
    scope = "all" if deal_id is None else deal_id
    kind = "all" if deal_id is None else "deal"
    pending_key = f"{prefix}chat_pending_{scope}"
    with st.container(key=f"{prefix}chatcard_{scope}"):
        if header:
            style.html('<div class="chat-head"><span class="chat-dot"></span>AI Teammate</div>')
        body = st.container(key=f"{prefix}chatbody_{scope}", height=460, border=False)
        with st.container(key=f"{prefix}chatbar_{scope}"):
            question = st.chat_input("Ask about all deals" if deal_id is None else "Ask about this deal",
                                     key=f"{prefix}chat_input_{scope}")
            with st.container(key=f"{prefix}chattools_{scope}", horizontal=True, vertical_alignment="center"):
                spoken = voice.render(f"{prefix}chat_{scope}", deal_id=deal_id)
                st.toggle("Web search", value=False, disabled=True, key=f"{prefix}web_search_{scope}")
            st.caption("Web search: coming in a later step.")
            limits_note = st.empty()  # filled in last, so it counts a message sent on this run
        # A checked transcript or a clicked suggestion is sent exactly like a typed message.
        question = question or spoken or st.session_state.pop(pending_key, None)
        with body:
            if not messages and not question:
                _show({"role": "assistant", "text": WELCOME[kind], "label": None,
                       "sources": [], "note": "", "deals": []}, f"{prefix}chatmsg_{scope}_welcome")
            for i, message in enumerate(messages):
                _show(message, f"{prefix}chatmsg_{scope}_{i}")
            if question:
                messages.append({"role": "user", "text": question})
                _show(messages[-1], f"{prefix}chatmsg_{scope}_{len(messages) - 1}")
                typing = st.empty()
                typing.html(TYPING)
                reply = get_answer(deal_id, question, messages[:-1])
                typing.empty()
                messages.append(reply)
                _show(reply, f"{prefix}chatmsg_{scope}_{len(messages) - 1}")
            with st.container(key=f"{prefix}chatchips_{scope}", horizontal=True):
                for n, suggestion in enumerate(SUGGESTIONS[kind]):
                    st.button(suggestion, key=f"{prefix}chatchip_{scope}_{n}", on_click=_ask_suggestion,
                              args=(pending_key, suggestion), help="Sends this question (1 AI request).")
        _scroll_to_newest(f"{prefix}chatbody_{scope}")
        limits_note.caption(ai_limits.summary())


def render(deal):
    st.caption("Answers come only from this deal's saved data: rent roll, T-12, flags and documents. "
               "Every answer is labelled. The AI is only contacted when you send a message.")
    render_chat(deal["id"], header=True)
