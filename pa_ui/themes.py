"""Colours. Pure Python (no Kivy) so it can be unit-tested anywhere.

There is no theme picker: the app has exactly two looks, switched with the sun/moon button in the
header. A look maps every colour ROLE to a "#rrggbb" string.
"""

import re

ROLES = ("bg", "bg2", "panel", "surface", "button", "button_text", "accent", "accent2", "text", "muted",
         "user", "bot", "sys", "input_bg", "input_text",
         "user_bubble", "user_bubble_text", "online")   # chat-app look: filled user bubble, green online dot

MODES = ("dark", "light")
DEFAULT_MODE = "dark"

COLORS = {
    # sun: light lavender-white
    "light": dict(
        bg="#f6f4ff", bg2="#e6e0ff", panel="#ffffff", surface="#ffffff", button="#e6e1fb", button_text="#231a4a",
        accent="#6d4ff0", accent2="#4338ca", text="#1c1536", muted="#5b4f8a", user="#4c2fd0", bot="#1c1536",
        sys="#a21caf", input_bg="#ffffff", input_text="#1c1536",
        user_bubble="#5b3fd9", user_bubble_text="#ffffff", online="#16a34a"),
    # moon: plain black (no purple)
    "dark": dict(
        bg="#000000", bg2="#0a0a0a", panel="#101010", surface="#161616", button="#262626", button_text="#f5f5f5",
        accent="#e4e4e7", accent2="#71717a", text="#f5f5f5", muted="#a3a3a3", user="#e4e4e7", bot="#f5f5f5",
        sys="#93c5fd", input_bg="#1a1a1a", input_text="#f5f5f5",
        user_bubble="#2563eb", user_bubble_text="#ffffff", online="#22c55e"),
}

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def valid_hex(s):
    return isinstance(s, str) and _HEX.match(s.strip()) is not None


def norm_hex(s):
    """'AABBCC' or '#aabbcc' -> '#aabbcc'. Raises ValueError for anything else."""
    m = _HEX.match(s.strip()) if isinstance(s, str) else None
    if not m:
        raise ValueError("not a 6-digit hex colour: %r" % (s,))
    return "#" + m.group(1).lower()


def hex_to_rgba(h, alpha=1.0):
    h = norm_hex(h)[1:]
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, alpha)


def rgba_to_hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v * 255)))) for v in c[:3])


def _lin(v):
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(h):
    r, g, b, _ = hex_to_rgba(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(a, b):
    """WCAG contrast ratio between two hex colours (1.0 .. 21.0)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def best_on(bg_hex):
    """Black or white, whichever reads better on bg_hex."""
    return "#000000" if contrast_ratio(bg_hex, "#000000") >= contrast_ratio(bg_hex, "#ffffff") else "#ffffff"


def mix(a, b, t):
    """Blend hex colour a toward b by t (0..1) -> hex."""
    ca, cb = hex_to_rgba(a), hex_to_rgba(b)
    return rgba_to_hex(tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(3)))


def resolve(mode):
    """Colours (role -> hex) of 'light' or 'dark'; anything else gives the default (dark)."""
    return dict(COLORS.get(mode, COLORS[DEFAULT_MODE]))


# (foreground role, background role, minimum ratio) pairs that must stay readable
READABILITY = (("text", "bg", 4.5), ("muted", "bg", 4.5), ("text", "bg2", 4.5), ("button_text", "button", 4.5),
               ("input_text", "input_bg", 4.5), ("bot", "surface", 4.5), ("user", "surface", 3.0),
               ("user", "bg", 3.0), ("sys", "bg", 3.0), ("sys", "surface", 3.0), ("text", "panel", 4.5),
               ("user_bubble_text", "user_bubble", 4.5), ("muted", "surface", 3.0))


def readability_problems(colors):
    out = []
    for fg, bg, need in READABILITY:
        r = contrast_ratio(colors[fg], colors[bg])
        if r < need:
            out.append((fg, bg, r, need))
    return out
