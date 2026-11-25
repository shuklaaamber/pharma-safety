"""Render user-supplied text as inert text inside Streamlit markdown widgets.

Report descriptions, chat messages and retrieved excerpts are untrusted. Rendered as
raw markdown, an image link such as ``![x](https://host/a.png)`` would make the
browser fetch an external URL. Backslash-escaping every ASCII punctuation character is
valid CommonMark and also disables Streamlit's ``:emoji:``, ``$math$`` and colour
directives, so the text shows exactly as typed.
"""
from __future__ import annotations

import string

_BACKSLASH = chr(92)


def escape_md(text: str) -> str:
    out: list[str] = []
    for ch in text or "":
        if ch in string.punctuation:
            out.append(_BACKSLASH + ch)
        elif ch == "\n":
            out.append("  \n")  # keep line breaks
        else:
            out.append(ch)
    return "".join(out)
