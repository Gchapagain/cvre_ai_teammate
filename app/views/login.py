"""Login: step 1 pick a role, step 2 sign in. The sign-in buttons stay locked until a role is chosen."""

import streamlit as st

from app import icons, queries, style

# role -> (icon, one line about what that role does)
ROLES = {
    "Agent": (icons.BRIEFCASE, "Brokers the deal and approves what goes to the client."),
    "Analyst": (icons.CHART, "Checks the numbers and prepares the pricing work."),
    "Administrator": (icons.SHIELD, "Manages users, roles and settings."),
}
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
.login-help {{ font-size: 0.85rem; color: var(--ink-soft); }}
.login-note {{ font-size: 0.8rem; color: var(--ink-soft); text-align: center; margin-top: var(--s1);
  padding-top: var(--s2); border-top: 1px solid var(--line); }}

/* Role cards: the whole card is the button (see the deal cards for how the click layer works). */
[class*="st-key-rolecard_"] {{ position: relative; border: 1.5px solid var(--line) !important; border-radius: var(--radius) !important;
  padding: 12px var(--s2) !important; gap: 0 !important; background: var(--surface); cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s; }}
[class*="st-key-rolecard_"]:hover {{ border-color: var(--green-mid) !important; box-shadow: var(--shadow-hover); }}
[class*="st-key-rolecard_"]:focus-within {{ box-shadow: var(--focus); }}
[class*="st-key-rolecard_on_"] {{ border: 2px solid var(--green) !important; background: var(--green-tint); }}
[class*="st-key-rolecard_"] * {{ position: static !important; }}
[class*="st-key-rolebtn_"] {{ height: 0; }}
[class*="st-key-rolebtn_"] button {{ min-height: 0; height: 0; padding: 0; border: none; background: none; }}
[class*="st-key-rolebtn_"] button p {{ font-size: 0; }}  /* the name is shown in the card; this keeps it for screen readers */
[class*="st-key-rolebtn_"] button::after {{ content: ""; position: absolute; inset: 0; z-index: 1; cursor: pointer; }}
.role {{ display: flex; align-items: center; gap: var(--s2); }}
.role .icon {{ display: flex; align-items: center; justify-content: center; width: 40px; height: 40px; flex: none;
  border-radius: 10px; background: var(--green-tint); color: var(--green); }}
[class*="st-key-rolecard_on_"] .role .icon {{ background: var(--green); color: #ffffff; }}
.role .name {{ font-weight: 600; color: var(--ink); }}
.role .line {{ font-size: 0.85rem; color: var(--ink-soft); }}
.role .tick {{ margin-left: auto; display: flex; align-items: center; justify-content: center; width: 24px; height: 24px;
  flex: none; border-radius: 50%; background: var(--green); color: #ffffff; }}

/* Sign-in buttons: full width, provider icon on the left. */
[class*="st-key-sign_in_"] button {{ width: 100%; min-height: 44px; gap: 10px; font-weight: 600; }}
[class*="st-key-sign_in_"] button::before {{ content: ""; width: 18px; height: 18px; flex: none;
  background: center / contain no-repeat; }}
.st-key-sign_in_google button::before {{ background-image: {icons.GOOGLE_URL}; }}
.st-key-sign_in_microsoft button::before {{ background-image: {icons.MICROSOFT_URL}; }}
[class*="st-key-sign_in_"] button:disabled {{ opacity: 0.55; cursor: not-allowed; }}
[class*="st-key-sign_in_"] button:disabled::before {{ filter: grayscale(1); }}
</style>
"""


def _choose(role):
    st.session_state.login_role = role


def _sign_in(role):
    st.session_state.user = queries.demo_user(role)
    st.session_state.page = "dashboard"


def _left_panel():
    points = "".join(f'<div class="point"><span class="icon">{icon}</span><span>{text}</span></div>'
                     for icon, text in POINTS)
    style.html(
        f'<div class="login-left"><div class="logo">{icons.SPARKLE}<span>CBRE AI Teammate</span></div>'
        '<div class="tagline">The AI drafts, flags and cites. A person always approves.</div>'
        f'{points}</div>'
    )


def _role_card(role, selected):
    icon, line = ROLES[role]
    slug = role.lower()
    with st.container(border=True, key=f"rolecard_{'on_' if selected else ''}{slug}"):
        tick = f'<span class="tick">{icons.CHECK}</span>' if selected else ""
        style.html(f'<div class="role"><span class="icon">{icon}</span><div><div class="name">{role}</div>'
                   f'<div class="line">{line}</div></div>{tick}</div>')
        st.button(role, key=f"rolebtn_{slug}", type="tertiary", on_click=_choose, args=(role,))


def render():
    style.html(PAGE_CSS)
    _left_panel()
    role = st.session_state.get("login_role")
    with st.container(key="login_card"):
        style.html('<div class="login-title">Welcome back</div>'
                   '<div class="login-sub">Sign in to review your deals.</div>')
        style.html('<div class="login-step">Step 1 · Choose your role</div>')
        for name in ROLES:
            _role_card(name, name == role)
        style.html('<div class="login-step">Step 2 · Sign in</div>')
        help_text = f"Signing in as {role}." if role else "Choose a role to continue"
        style.html(f'<div class="login-help">{help_text}</div>')
        for provider in ("Google", "Microsoft"):
            st.button(f"Continue with {provider}", key=f"sign_in_{provider.lower()}",
                      disabled=role is None, on_click=_sign_in, args=(role,), width="stretch")
        style.html('<div class="login-note">Demo login. No real sign-in happens yet.</div>')
