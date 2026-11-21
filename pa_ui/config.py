"""Lazey's saved GUI setting: which theme is selected.

Pure Python. The screen layout and the placement of the buttons are fixed by this module
(DEFAULT_LAYOUT / DEFAULT_BUTTONS); only the theme is stored on the phone, and whatever is read back
from disk is validated, so a damaged or hand-edited file can never break the screen.

Where a button lives:
    menu         a row in the slide-out menu (the hamburger, top corner)
    input_left   inside the typing bar, before the text box
    input_right  inside the typing bar, after the text box
"""
import json
import os

from . import themes

APP_NAME = "Lazey"
TAGLINE = "Your Personal AI Assistant"

# id -> (label, icon, handler name on the app)
BUTTONS = {
    "theme": ("Theme", "palette", "show_style"),
    "calendar": ("Calendar", "calendar", "show_calendar"),
    "prefs": ("Preferences", "sliders", "show_prefs"),
    "voice": ("Voice", "speaker", "on_voice"),
    "plus": ("Quick prompts", "plus", "show_quick"),
    "mic": ("Mic", "mic", "on_mic"),
    "send": ("Send", "send", "send"),
}

DEFAULT_LAYOUT = dict(brand_align="center", menu_side="left", input_position="bottom", show_hero=True,
                      show_tagline=True, bubbles="bubbles", btn_h=56, radius=22, font_scale=1.0, spacing=8)

DEFAULT_BUTTONS = [  # (id, region) in display order
    ("theme", "menu"), ("calendar", "menu"), ("prefs", "menu"), ("voice", "menu"),
    ("plus", "input_left"), ("mic", "input_right"), ("send", "input_right")]


def default_config():
    return {"version": 3, "theme": themes.DEFAULT_THEME, "layout": dict(DEFAULT_LAYOUT),
            "buttons": [{"id": bid, "region": region, "icon": BUTTONS[bid][1], "label": BUTTONS[bid][0]}
                        for bid, region in DEFAULT_BUTTONS]}


def normalize(raw):
    """A valid config from whatever `raw` contains. Only the theme is taken from `raw`; layout and
    buttons are always the fixed defaults (older files may carry layout/colour edits; they are ignored)."""
    cfg = default_config()
    theme = raw.get("theme") if isinstance(raw, dict) else None
    if isinstance(theme, str) and theme in themes.BUILTIN:
        cfg["theme"] = theme
    return cfg


def set_theme(cfg, theme_id):
    new = dict(cfg)
    new["theme"] = theme_id
    return normalize(new)


def buttons_in(cfg, region):
    return [b for b in cfg["buttons"] if b["region"] == region]


def current_colors(cfg):
    return themes.resolve(cfg["theme"])


# ---------- storage ----------
class ConfigStore:
    """JSON file in the app's private data dir holding just the theme. Writes are atomic; a corrupt
    file is kept as .bad and the default theme is used."""

    def __init__(self, directory, name="ui_config.json"):
        self.path = os.path.join(directory, name)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                return normalize(json.load(fh))
        except FileNotFoundError:
            return default_config()
        except (ValueError, OSError):
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            return default_config()

    def save(self, cfg):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": cfg.get("version", 3), "theme": cfg["theme"]}, fh, indent=1)
        os.replace(tmp, self.path)
