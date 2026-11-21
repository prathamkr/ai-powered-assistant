"""The quick-prompt list (the "+" button): defaults, adding your own, deleting, and saving.

Pure Python (no Kivy). Each prompt is {"label": text shown on its button, "fill": text put in the typing
box}. For the built-in starters the two differ ("Note:" fills "Note: " so you can keep typing); for your own
prompts they are the same.
"""
import json
import os

DEFAULTS = (("Remember", "Remember "), ("Note:", "Note: "),
            ("Call mummy from sim 1", "Call mummy from sim 1"),
            ("Show photos from yesterday", "Show photos from yesterday"))
MAX_LEN = 80      # characters in one prompt
MAX_ITEMS = 30    # prompts in the list


def default_prompts():
    return [{"label": label, "fill": fill} for label, fill in DEFAULTS]


def normalize(raw):
    """A clean list from whatever was read. Not a list -> the defaults; an empty list stays empty
    (the user may have deleted everything)."""
    if not isinstance(raw, list):
        return default_prompts()
    out = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        label, fill = it.get("label"), it.get("fill")
        if not isinstance(label, str) or not label.strip():
            continue
        label = label.strip()[:MAX_LEN]
        fill = fill if isinstance(fill, str) and fill.strip() else label
        out.append({"label": label, "fill": fill[:MAX_LEN + 1]})
        if len(out) >= MAX_ITEMS:
            break
    return out


def add(items, text):
    """New list with `text` appended. Raises ValueError with a message that can be shown to the user."""
    text = " ".join((text or "").split())      # trim and collapse spaces
    if not text:
        raise ValueError("Type a prompt first.")
    if len(text) > MAX_LEN:
        raise ValueError("Keep it under %d characters." % MAX_LEN)
    if len(items) >= MAX_ITEMS:
        raise ValueError("You can keep up to %d prompts. Delete one first." % MAX_ITEMS)
    if any(it["label"].lower() == text.lower() for it in items):
        raise ValueError("That prompt is already in the list.")
    return list(items) + [{"label": text, "fill": text}]


def delete(items, index):
    """New list without the prompt at `index` (an out-of-range index changes nothing)."""
    if not 0 <= index < len(items):
        return list(items)
    return [it for i, it in enumerate(items) if i != index]


class PromptStore:
    """JSON file in the app's private folder. Writes are atomic; a damaged file is kept as .bad."""

    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                return normalize(json.load(fh))
        except FileNotFoundError:
            return default_prompts()
        except (ValueError, OSError):
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            return default_prompts()

    def save(self, items):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(items, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)
