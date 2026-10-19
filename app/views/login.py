"""Login for brokers: a brand panel on the left and a sign-in card on the right. Demo sign-in only."""

import streamlit as st

from app import icons, queries, style

ROLE = "Broker"  # the only user type
POINTS = [
    (icons.FLAG, "Flags problems, never hides them"),
    (icons.CITE, "Cites where every number came from"),
    (icons.APPROVE, "A person approves every result"),
]

# Layout that only applies while the login page is showing: a fixed left panel and a centred card.
PAGE_CSS = f"""
<style>
.block-container {{ max-width: none !important; padding: 0 var(--s4) var(--s4) calc(50% + var(--s4)) !important; }}
.login-left {{ position: fixed; inset: 0 50% 0 0; background: var(--green-dark); color: #ffffff; display: flex;
  flex-direction: column; justify-content: center; padding: 0 clamp(40px, 7vw, 112px); }}
.login-left .logo {{ display: flex; align-items: center; gap: 14px; }}
.login-left .logo svg {{ width: 40px; height: 40px; }}
.login-left .logo span {{ font-family: 'Fraunces', Georgia, serif; font-size: 2.4rem; font-weight: 600; color: #ffffff; }}
.login-left .tagline {{ font-size: 1.15rem; line-height: 1.6; color: #dfe7e2; margin: var(--s3) 0 var(--s5); max-width: 30rem; }}
.login-left .point {{ display: flex; align-items: center; gap: var(--s2); margin-bottom: var(--s3); font-size: 1.02rem; }}
.login-left .point .icon {{ display: flex; align-items: center; justify-content: center; width: 40px; height: 40px;
  flex: none; border-radius: 50%; background: rgba(201, 162, 39, 0.16); color: var(--gold); }}

/* Centred in the right half, whatever the window height. It scrolls inside itself on a short screen. */
.st-key-login_card {{ position: fixed; top: 50%; left: 75%; transform: translate(-50%, -50%);
  width: min(440px, calc(50vw - 48px)) !important; max-height: calc(100vh - 32px); overflow-y: auto;
  background: var(--surface); border: 1px solid var(--line); border-radius: 16px;
  box-shadow: 0 12px 40px rgba(19, 39, 30, 0.12); padding: var(--s4) 40px !important; gap: 12px !important; }}
.st-key-login_card [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
.login-title {{ font-family: 'Fraunces', Georgia, serif; font-size: 1.9rem; font-weight: 600; color: var(--green); }}
.login-sub {{ color: var(--ink-soft); margin-top: 4px; }}
.login-step {{ font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--ink-soft); margin-top: var(--s2); }}
.login-note {{ font-size: 0.8rem; color: var(--ink-soft); text-align: center; margin-top: var(--s1);
  padding-top: var(--s2); border-top: 1px solid var(--line); }}

/* Sign-in buttons: full width, provider icon on the left. */
[class*="st-key-sign_in_"] button {{ width: 100%; min-height: 44px; gap: 10px; font-weight: 600; }}
[class*="st-key-sign_in_"] button::before {{ content: ""; width: 18px; height: 18px; flex: none;
  background: center / contain no-repeat; }}
.st-key-sign_in_google button::before {{ background-image: {icons.GOOGLE_URL}; }}
.st-key-sign_in_microsoft button::before {{ background-image: {icons.MICROSOFT_URL}; }}
</style>
"""


def _sign_in():
    st.session_state.user = queries.demo_user(ROLE)
    st.session_state.page = "dashboard"


def _left_panel():
    points = "".join(f'<div class="point"><span class="icon">{icon}</span><span>{text}</span></div>'
                     for icon, text in POINTS)
    style.html(
        f'<div class="login-left"><div class="logo">{icons.SPARKLE}<span>CBRE AI Teammate</span></div>'
        '<div class="tagline">The AI drafts, flags and cites. A person always approves.</div>'
        f'{points}</div>'
    )


def render():
    style.html(PAGE_CSS)
    _left_panel()
    with st.container(key="login_card"):
        style.html('<div class="login-title">Welcome back</div>'
                   '<div class="login-sub">Sign in to review your deals.</div>'
                   '<div class="login-step">Broker sign-in</div>')
        ready = queries.demo_user(ROLE) is not None
        if not ready:  # a database seeded before Broker became the only role
            st.warning("The sample data is from an older version. Stop the app, run "
                       "`.venv/bin/python seed.py --reset`, then start it again.")
        for provider in ("Google", "Microsoft"):
            st.button(f"Continue with {provider}", key=f"sign_in_{provider.lower()}", on_click=_sign_in,
                      width="stretch", disabled=not ready)
        style.html('<div class="login-note">Demo login. No real sign-in happens yet.</div>')
