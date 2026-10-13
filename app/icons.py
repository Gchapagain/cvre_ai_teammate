"""Small inline SVG icons. Line icons take the colour of the text around them."""

from urllib.parse import quote


def _line(paths, size=20):
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths}</svg>')


# A four-point sparkle in the gold accent, used wherever the AI is the subject.
SPARKLE = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#c9a227" '
           'd="M12 1.5l2.6 7.9 7.9 2.6-7.9 2.6-2.6 7.9-2.6-7.9-7.9-2.6 7.9-2.6z"/></svg>')

FLAG = _line('<path d="M5 21V4"/><path d="M5 4h12l-2.5 4L17 12H5"/>')
CITE = _line('<path d="M7 3h8l4 4v14H7z"/><path d="M15 3v4h4"/><path d="M10 12h6M10 16h6"/>')
APPROVE = _line('<circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6 1.6 0 3 .3 4.200 1"/><path d="M15 18l2.500 2.500L22 16"/>')
BRIEFCASE = _line('<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><path d="M3 13h18"/>', 22)
CHART = _line('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>', 22)
SHIELD = _line('<path d="M12 3l8 3v6c0 5-3.500 8-8 9-4.500-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>', 22)
CHECK = _line('<path d="M5 12.500l4.500 4.500L19 7"/>', 16)

_GOOGLE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
           '<path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>'
           '<path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>'
           '<path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>'
           '<path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>')
_MICROSOFT = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
              '<rect x="2" y="2" width="9.500" height="9.500" fill="#F25022"/><rect x="12.500" y="2" width="9.500" height="9.500" fill="#7FBA00"/>'
              '<rect x="2" y="12.500" width="9.500" height="9.500" fill="#00A4EF"/><rect x="12.500" y="12.500" width="9.500" height="9.500" fill="#FFB900"/></svg>')


def css_url(svg):
    """An SVG as a CSS url(), for icons that have to sit inside a Streamlit button."""
    return f"url(\"data:image/svg+xml,{quote(svg)}\")"


GOOGLE_URL = css_url(_GOOGLE)
MICROSOFT_URL = css_url(_MICROSOFT)
SPARKLE_URL = css_url(SPARKLE.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '))
