"""Colour themes and backgrounds. Pure Python (no Kivy) so it can be unit-tested anywhere.

A theme maps every colour ROLE to a "#rrggbb" string. A BACKGROUND swaps only the background-ish
roles (bg, bg2, panel, surface, input_bg) so any dark theme can sit on any of 9 backdrops. The user
can also override single roles ("custom") or save the result as their own named theme.
"""
import re

# role -> (label shown in the editor, short hint)
ROLES = {
    "bg": ("Background (top)", "Top of the screen"),
    "bg2": ("Background (bottom)", "Bottom of the screen"),
    "panel": ("Menus and pop-ups", "Behind dialogs"),
    "surface": ("Cards and bubbles", "Typing bar, replies"),
    "button": ("Buttons", "Button fill"),
    "button_text": ("Button text", "Text and icons on buttons"),
    "accent": ("Accent", "Glow, highlights, Send"),
    "accent2": ("Accent (second)", "Other end of the gradient"),
    "text": ("Text", "Headings and general text"),
    "muted": ("Soft text", "Tagline, hints"),
    "user": ("Your messages", "Text you sent"),
    "bot": ("Replies", "Assistant replies"),
    "sys": ("Notes", "Status and warnings"),
    "input_bg": ("Input fields", "Text boxes in dialogs"),
    "input_text": ("Typed text", "Text you type"),
}
BG_ROLES = ("bg", "bg2", "panel", "surface", "input_bg")

BUILTIN = {
    "violet": ("Violet", dict(
        bg="#0b0816", bg2="#150d2e", panel="#17112b", surface="#1d1640", button="#2a2060", button_text="#f1ecff",
        accent="#8b5cf6", accent2="#4f46e5", text="#f4f1ff", muted="#b9a9f0", user="#c4b5fd", bot="#f4f1ff",
        sys="#fcd34d", input_bg="#241c4d", input_text="#f4f1ff")),
    "ocean": ("Ocean", dict(
        bg="#06141f", bg2="#0a2a3f", panel="#0d2233", surface="#12324a", button="#1c4a69", button_text="#e6f6ff",
        accent="#22b8f0", accent2="#2563eb", text="#eaf7ff", muted="#9ccbe6", user="#7dd3fc", bot="#eaf7ff",
        sys="#fcd34d", input_bg="#123a56", input_text="#eaf7ff")),
    "emerald": ("Emerald", dict(
        bg="#06140e", bg2="#0b2a1d", panel="#0e2318", surface="#143324", button="#1f5238", button_text="#e8fff2",
        accent="#22c55e", accent2="#0d9488", text="#ecfff4", muted="#9fd8b8", user="#86efac", bot="#ecfff4",
        sys="#fde68a", input_bg="#17402c", input_text="#ecfff4")),
    "rose": ("Rose", dict(
        bg="#170812", bg2="#2e0f24", panel="#26101e", surface="#35162a", button="#5b2347", button_text="#fff0f7",
        accent="#f43f8e", accent2="#c026d3", text="#fff0f7", muted="#f0a9cb", user="#fbb6d6", bot="#fff0f7",
        sys="#fcd34d", input_bg="#43203a", input_text="#fff0f7")),
    "amber": ("Amber", dict(
        bg="#140e05", bg2="#2b1c08", panel="#241809", surface="#33220c", button="#5a3b12", button_text="#fff6e5",
        accent="#f59e0b", accent2="#ea580c", text="#fff7ea", muted="#e8c48a", user="#fcd34d", bot="#fff7ea",
        sys="#fb923c", input_bg="#43300f", input_text="#fff7ea")),
    "graphite": ("Graphite", dict(
        bg="#0d0e10", bg2="#1a1c20", panel="#191b1f", surface="#23262b", button="#353941", button_text="#f3f4f6",
        accent="#94a3b8", accent2="#64748b", text="#f3f4f6", muted="#a8b0bd", user="#cbd5e1", bot="#f3f4f6",
        sys="#fcd34d", input_bg="#2b2f36", input_text="#f3f4f6")),
    "daylight": ("Daylight", dict(
        bg="#f6f4ff", bg2="#e6e0ff", panel="#ffffff", surface="#ffffff", button="#e6e1fb", button_text="#231a4a",
        accent="#6d4ff0", accent2="#4338ca", text="#1c1536", muted="#5b4f8a", user="#4c2fd0", bot="#1c1536",
        sys="#8a4f00", input_bg="#ffffff", input_text="#1c1536")),
    "contrast": ("High contrast", dict(
        bg="#000000", bg2="#000000", panel="#000000", surface="#141414", button="#ffff00", button_text="#000000",
        accent="#00ffff", accent2="#00bfff", text="#ffffff", muted="#e0e0e0", user="#00ffff", bot="#ffffff",
        sys="#ffff00", input_bg="#ffffff", input_text="#000000")),
}
DEFAULT_THEME = "violet"
SAVED_PREFIX = "user:"
MAX_SAVED = 12

# Nine backdrops for dark themes (id -> (name, colours for BG_ROLES))
BACKGROUNDS = {
    "violet": ("Deep violet", dict(bg="#0b0816", bg2="#150d2e", panel="#17112b", surface="#1d1640", input_bg="#241c4d")),
    "midnight": ("Midnight blue", dict(bg="#060d1c", bg2="#0c1a3a", panel="#0f1930", surface="#15244a", input_bg="#1b2d5c")),
    "black": ("AMOLED black", dict(bg="#000000", bg2="#0a0a0f", panel="#0c0c10", surface="#15151b", input_bg="#1d1d25")),
    "graphite": ("Graphite", dict(bg="#0d0e10", bg2="#1a1c20", panel="#191b1f", surface="#23262b", input_bg="#2b2f36")),
    "forest": ("Forest night", dict(bg="#06140e", bg2="#0b2a1d", panel="#0e2318", surface="#143324", input_bg="#17402c")),
    "wine": ("Wine", dict(bg="#170812", bg2="#2e0f24", panel="#26101e", surface="#35162a", input_bg="#43203a")),
    "teal": ("Deep teal", dict(bg="#04141a", bg2="#08323b", panel="#0b2229", surface="#103a45", input_bg="#144854")),
    "slate": ("Slate", dict(bg="#0f1420", bg2="#1e2a3f", panel="#182032", surface="#232f46", input_bg="#2c3a56")),
    "ember": ("Ember", dict(bg="#140a06", bg2="#2e150a", panel="#241209", surface="#351c0e", input_bg="#43250f")),
}
BACKGROUND_DEFAULT = "theme"  # "use the theme's own background"

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


def is_light(colors):
    return luminance(colors["bg"]) > 0.35


def backdrop_applies(colors):
    """Backdrops are dark: only offered for light-on-dark themes (not Daylight, not High contrast)."""
    return not is_light(colors) and luminance(colors["input_text"]) > 0.5


def theme_ids(saved):
    return list(BUILTIN) + [SAVED_PREFIX + n for n in saved]


def theme_name(theme_id, saved):
    if theme_id in BUILTIN:
        return BUILTIN[theme_id][0]
    if theme_id.startswith(SAVED_PREFIX):
        return theme_id[len(SAVED_PREFIX):]
    return theme_id


def base_colors(theme_id, saved):
    """Full role->hex dict of a theme; unknown ids fall back to the default theme."""
    if theme_id in BUILTIN:
        return dict(BUILTIN[theme_id][1])
    if theme_id.startswith(SAVED_PREFIX) and theme_id[len(SAVED_PREFIX):] in saved:
        base = dict(BUILTIN[DEFAULT_THEME][1])
        base.update(saved[theme_id[len(SAVED_PREFIX):]])
        return base
    return dict(BUILTIN[DEFAULT_THEME][1])


def resolve(theme_id, custom, saved, background=BACKGROUND_DEFAULT):
    """Final colours = theme, then the chosen backdrop (dark themes only), then per-role overrides."""
    colors = base_colors(theme_id, saved)
    if background in BACKGROUNDS and backdrop_applies(colors):
        colors.update(BACKGROUNDS[background][1])
    for role, value in (custom or {}).items():
        if role in ROLES and valid_hex(value):
            colors[role] = norm_hex(value)
    return colors


# (foreground role, background role, minimum ratio) pairs the editor warns about
READABILITY = (("text", "bg", 4.5), ("muted", "bg", 4.5), ("text", "bg2", 4.5), ("button_text", "button", 4.5),
               ("input_text", "input_bg", 4.5), ("bot", "surface", 4.5), ("user", "surface", 3.0),
               ("user", "bg", 3.0), ("sys", "bg", 3.0), ("text", "panel", 4.5))


def readability_problems(colors):
    out = []
    for fg, bg, need in READABILITY:
        r = contrast_ratio(colors[fg], colors[bg])
        if r < need:
            out.append((fg, bg, r, need))
    return out
