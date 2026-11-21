"""The saved GUI configuration: theme, backdrop, colour overrides, layout options and button arrangement.

Pure Python. Every value that comes from disk or from the editor passes through normalize(), so a
hand-edited or corrupt file can never produce a screen the user cannot recover from. In particular
the Theme entry (the way back into the editor) can never be hidden.

Where a button can live:
    menu         a row in the slide-out menu (the hamburger, top corner)
    input_left   inside the typing bar, before the text box
    input_right  inside the typing bar, after the text box
    hidden       nowhere (the Theme entry cannot be hidden)
"""
import copy
import json
import os

from . import themes
from .iconset import CHOOSABLE

APP_NAME = "Pacsit"
TAGLINE = "Your Personal AI Assistant"

# id -> (default label, default icon, handler name on the app)
BUTTONS = {
    "theme": ("Theme", "palette", "show_style"),
    "calendar": ("Calendar", "calendar", "show_calendar"),
    "prefs": ("Preferences", "sliders", "show_prefs"),
    "voice": ("Voice", "speaker", "on_voice"),
    "plus": ("Quick prompts", "plus", "show_quick"),
    "mic": ("Mic", "mic", "on_mic"),
    "send": ("Send", "send", "send"),
}
REGIONS = ("menu", "input_left", "input_right", "hidden")
REGION_NAMES = {"menu": "Menu", "input_left": "Bar: left", "input_right": "Bar: right", "hidden": "Hidden"}
ALWAYS_VISIBLE = "theme"
LABEL_MAX = 20

ALIGNS = ("center", "left")
SIDES = ("left", "right")
VERTICAL = ("top", "bottom")
BUBBLES = ("bubbles", "plain")

NUM_LIMITS = {"btn_h": (44, 72), "radius": (6, 30), "font_scale": (0.85, 1.4), "spacing": (4, 14)}

DEFAULT_LAYOUT = dict(brand_align="center", menu_side="left", input_position="bottom", show_hero=True,
                      show_tagline=True, bubbles="bubbles", btn_h=56, radius=22, font_scale=1.0, spacing=8)

DEFAULT_BUTTONS = [  # (id, region) in display order
    ("theme", "menu"), ("calendar", "menu"), ("prefs", "menu"), ("voice", "menu"),
    ("plus", "input_left"), ("mic", "input_right"), ("send", "input_right")]

PRESETS = {
    "pacsit": ("Pacsit", dict(), DEFAULT_BUTTONS),
    "minimal": ("Minimal", dict(show_hero=False, show_tagline=False, bubbles="plain", radius=12, btn_h=48),
                DEFAULT_BUTTONS),
    "big": ("Big touch", dict(btn_h=68, radius=26, font_scale=1.2, spacing=10), DEFAULT_BUTTONS),
    "lefty": ("Left-handed", dict(menu_side="right"),
              [("theme", "menu"), ("calendar", "menu"), ("prefs", "menu"), ("voice", "menu"),
               ("mic", "input_left"), ("send", "input_left"), ("plus", "input_right")]),
    "top": ("Typing bar on top", dict(input_position="top", brand_align="left"), DEFAULT_BUTTONS),
}


def default_config():
    cfg = {"version": 2, "theme": themes.DEFAULT_THEME, "background": themes.BACKGROUND_DEFAULT, "custom": {},
           "saved_themes": {}, "layout": dict(DEFAULT_LAYOUT), "buttons": []}
    for bid, region in DEFAULT_BUTTONS:
        cfg["buttons"].append(_button(bid, region))
    return cfg


def _button(bid, region):
    label, icon, _ = BUTTONS[bid]
    return {"id": bid, "region": region, "icon": icon, "label": label}


def _num(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def normalize(raw):
    """Return a fully valid config built from whatever `raw` contains."""
    cfg = default_config()
    if not isinstance(raw, dict):
        return cfg

    saved = {}
    if isinstance(raw.get("saved_themes"), dict):
        for name, cols in raw["saved_themes"].items():
            if isinstance(name, str) and name.strip() and isinstance(cols, dict) and len(saved) < themes.MAX_SAVED:
                clean = {r: themes.norm_hex(v) for r, v in cols.items() if r in themes.ROLES and themes.valid_hex(v)}
                saved[name.strip()[:24]] = clean
    cfg["saved_themes"] = saved

    t = raw.get("theme")
    cfg["theme"] = t if isinstance(t, str) and t in themes.theme_ids(saved) else themes.DEFAULT_THEME
    b = raw.get("background")
    cfg["background"] = b if isinstance(b, str) and b in themes.BACKGROUNDS else themes.BACKGROUND_DEFAULT

    if isinstance(raw.get("custom"), dict):
        cfg["custom"] = {r: themes.norm_hex(v) for r, v in raw["custom"].items()
                         if r in themes.ROLES and themes.valid_hex(v)}

    lay = raw.get("layout") if isinstance(raw.get("layout"), dict) else {}
    out = dict(DEFAULT_LAYOUT)
    for key, allowed in (("brand_align", ALIGNS), ("menu_side", SIDES), ("input_position", VERTICAL),
                         ("bubbles", BUBBLES)):
        if lay.get(key) in allowed:
            out[key] = lay[key]
    for key in ("show_hero", "show_tagline"):
        if isinstance(lay.get(key), bool):
            out[key] = lay[key]
    for key, (lo, hi) in NUM_LIMITS.items():
        v = _num(lay.get(key), lo, hi, DEFAULT_LAYOUT[key])
        out[key] = int(round(v)) if key != "font_scale" else round(v, 2)
    cfg["layout"] = out

    # buttons: keep the user's order and settings; every known id appears exactly once
    seen, buttons = set(), []
    for item in raw.get("buttons") if isinstance(raw.get("buttons"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] not in BUTTONS                 or item["id"] in seen:
            continue
        seen.add(item["id"])
        b = _button(item["id"], dict(DEFAULT_BUTTONS)[item["id"]])
        if item.get("region") in REGIONS:
            b["region"] = item["region"]
        if item.get("icon") in CHOOSABLE:
            b["icon"] = item["icon"]
        lab = item.get("label")
        if isinstance(lab, str) and lab.strip():
            b["label"] = lab.strip()[:LABEL_MAX]
        buttons.append(b)
    for bid, region in DEFAULT_BUTTONS:
        if bid not in seen:
            buttons.append(_button(bid, region))
    for b in buttons:
        if b["id"] == ALWAYS_VISIBLE and b["region"] == "hidden":
            b["region"] = "menu"
    cfg["buttons"] = buttons
    return cfg


# ---------- edits (all return a new normalized config) ----------
def buttons_in(cfg, region):
    return [b for b in cfg["buttons"] if b["region"] == region]


def _edit(cfg, fn):
    new = copy.deepcopy(cfg)
    fn(new)
    return normalize(new)


def _find(cfg, bid):
    return next(b for b in cfg["buttons"] if b["id"] == bid)


def set_theme(cfg, theme_id):
    def f(c):
        c["theme"], c["custom"], c["background"] = theme_id, {}, themes.BACKGROUND_DEFAULT
    return _edit(cfg, f)


def set_background(cfg, background):
    """Pick a backdrop. Colour overrides on the background roles are dropped so the pick is visible."""
    def f(c):
        c["background"] = background
        c["custom"] = {r: v for r, v in c["custom"].items() if r not in themes.BG_ROLES}
    return _edit(cfg, f)


def set_color(cfg, role, value):
    def f(c):
        c["custom"][role] = value
    return _edit(cfg, f)


def clear_colors(cfg):
    return _edit(cfg, lambda c: c.__setitem__("custom", {}))


def current_colors(cfg):
    return themes.resolve(cfg["theme"], cfg["custom"], cfg["saved_themes"], cfg["background"])


def save_current_theme(cfg, name):
    name = (name or "").strip()[:24]
    if not name:
        raise ValueError("Give the theme a name first.")

    def f(c):
        if name not in c["saved_themes"] and len(c["saved_themes"]) >= themes.MAX_SAVED:
            raise ValueError("You can keep up to %d saved themes. Delete one first." % themes.MAX_SAVED)
        c["saved_themes"][name] = current_colors(c)
        c["theme"], c["custom"], c["background"] = themes.SAVED_PREFIX + name, {}, themes.BACKGROUND_DEFAULT
    return _edit(cfg, f)


def delete_saved_theme(cfg, name):
    def f(c):
        c["saved_themes"].pop(name, None)
        if c["theme"] == themes.SAVED_PREFIX + name:
            c["theme"] = themes.DEFAULT_THEME
    return _edit(cfg, f)


def set_layout(cfg, **kw):
    def f(c):
        c["layout"].update(kw)
    return _edit(cfg, f)


def apply_preset(cfg, preset_id):
    _, lay, arrangement = PRESETS[preset_id]

    def f(c):
        c["layout"] = dict(DEFAULT_LAYOUT, **lay)
        old = {b["id"]: b for b in c["buttons"]}
        c["buttons"] = []
        for bid, region in arrangement:  # keep the user's icons/labels, change only the position
            b = dict(old.get(bid) or _button(bid, region))
            b["region"] = region
            c["buttons"].append(b)
    return _edit(cfg, f)


def set_button(cfg, bid, **kw):
    def f(c):
        _find(c, bid).update(kw)
    return _edit(cfg, f)


def cycle_region(cfg, bid):
    order = [r for r in REGIONS if bid != ALWAYS_VISIBLE or r != "hidden"]
    cur = _find(cfg, bid)["region"]
    nxt = order[(order.index(cur) + 1) % len(order)]
    return set_button(cfg, bid, region=nxt)


def move_button(cfg, bid, delta):
    """Move a button earlier (-1) or later (+1) among the buttons of its own region."""
    def f(c):
        b = _find(c, bid)
        same = [x for x in c["buttons"] if x["region"] == b["region"]]
        i = same.index(b)
        j = i + delta
        if 0 <= j < len(same):
            a, z = c["buttons"].index(same[i]), c["buttons"].index(same[j])
            c["buttons"][a], c["buttons"][z] = c["buttons"][z], c["buttons"][a]
    return _edit(cfg, f)


def reset_buttons(cfg):
    def f(c):
        c["buttons"] = [_button(bid, r) for bid, r in DEFAULT_BUTTONS]
    return _edit(cfg, f)


# ---------- storage ----------
class ConfigStore:
    """JSON file in the app's private data dir. Writes are atomic; a corrupt file is kept as .bad."""

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
            json.dump(cfg, fh, indent=1)
        os.replace(tmp, self.path)
