"""Voice: platform-independent parts (ported from the PocketMind Voice branch).

- VoiceProfile presets (Nova/Atlas/Echo/Luna/Spark): pitch + speed + volume + which installed
  voice to use. They are presets for the phone's own TextToSpeech, not different neural voices.
- VoiceSettings: persisted as a small plain JSON file in the app's private folder. It holds no
  personal data (only voice choices), so it is not encrypted.
- chunk(): turns a reply into short sentence-sized pieces so speech starts fast and stops cleanly.

The Android engines live in adapters/voice_android.py. Nothing here touches the network.
"""
import json
import os
import re
from dataclasses import asdict, dataclass

LANGUAGE = "en-IN"  # Indian English: the recognizer writes Hinglish in Latin letters ("rahul ko call karo")
PITCH_MIN, PITCH_MAX = 0.7, 1.4
RATE_MIN, RATE_MAX = 0.6, 1.6
SPEAK_MODES = ("voice", "always", "off")  # speak replies: after voice input / always / never


@dataclass(frozen=True)
class VoiceProfile:
    id: str
    name: str
    tagline: str
    pitch: float
    rate: float
    volume: float
    voice_index: int  # which installed voice of the language to use (wraps around)


PROFILES = (
    VoiceProfile("nova", "Nova", "Warm and friendly", 1.04, 1.0, 1.0, 0),
    VoiceProfile("atlas", "Atlas", "Deep and confident", 0.84, 0.94, 1.0, 1),
    VoiceProfile("echo", "Echo", "Calm and professional", 1.0, 1.0, 1.0, 2),
    VoiceProfile("luna", "Luna", "Soft and soothing", 1.06, 0.88, 0.9, 3),
    VoiceProfile("spark", "Spark", "Energetic and expressive", 1.12, 1.14, 1.0, 4),
)


def profile(pid):
    return next((p for p in PROFILES if p.id == pid), PROFILES[0])


def _clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))


@dataclass
class VoiceSettings:
    profile_id: str = "nova"
    pitch: float = 1.04
    rate: float = 1.0
    volume: float = 1.0
    voice_index: int = 0
    speak_mode: str = "voice"
    prefer_offline: bool = True

    def use_profile(self, pid):
        p = profile(pid)
        self.profile_id, self.pitch, self.rate = p.id, p.pitch, p.rate
        self.volume, self.voice_index = p.volume, p.voice_index

    def sanitized(self):
        """Values from disk are untrusted: clamp and fall back to defaults."""
        d = VoiceSettings()
        d.use_profile(self.profile_id if any(p.id == self.profile_id for p in PROFILES) else "nova")
        try:
            d.pitch = _clamp(self.pitch, PITCH_MIN, PITCH_MAX)
            d.rate = _clamp(self.rate, RATE_MIN, RATE_MAX)
            d.volume = _clamp(self.volume, 0.0, 1.0)
            d.voice_index = int(self.voice_index) % 50
        except (TypeError, ValueError):
            pass
        d.speak_mode = self.speak_mode if self.speak_mode in SPEAK_MODES else "voice"
        d.prefer_offline = bool(self.prefer_offline)
        return d


def load_settings(path):
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        known = {k: raw[k] for k in VoiceSettings.__dataclass_fields__ if k in raw}
        return VoiceSettings(**known).sanitized()
    except (OSError, ValueError, TypeError):
        return VoiceSettings()


def save_settings(path, s):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(s.sanitized()), f)
    os.replace(tmp, path)


def should_speak(mode, from_voice):
    return mode == "always" or (mode == "voice" and from_voice)


# ---------- text -> speakable sentences (port of SentenceChunker) ----------
MAX_CHUNK, MIN_CHUNK = 260, 24
_ABBR = ("mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "no.")
_SENT = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")


def clean(raw):
    s = re.sub(r"```.*?```", " code block omitted. ", raw or "", flags=re.S)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"https?://\S+", "link", s)
    s = re.sub(r"(?m)^\s{0,3}(#{1,6}|>|[-*+]|\d+[.)])\s+", "", s)
    s = re.sub(r"[*_~]{1,3}", "", s)
    s = re.sub(r"[\U0001F000-\U0001FAFF☀-➿‍️]", "", s)
    s = s.replace(" ", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def _hard_wrap(s):
    out = []
    while len(s) > MAX_CHUNK:
        win = s[:MAX_CHUNK]
        cut = max(win.rfind(","), win.rfind(";"), win.rfind(":"))
        if cut < MAX_CHUNK // 3:
            cut = win.rfind(" ")
        if cut <= 0:
            cut = MAX_CHUNK - 1
        out.append(s[:cut + 1].strip())
        s = s[cut + 1:].strip()
    if s:
        out.append(s)
    return out


def chunk(raw):
    """[(text, paragraph_end)] in speaking order."""
    text = clean(raw)
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    out = []
    for pi, para in enumerate(paras):
        sents = []
        for part in (x.strip() for x in _SENT.split(para) if x.strip()):
            if sents and sents[-1].lower().endswith(_ABBR):
                sents[-1] += " " + part
            elif sents and len(sents[-1]) < MIN_CHUNK and len(sents[-1]) + len(part) < MAX_CHUNK:
                sents[-1] += " " + part
            else:
                sents.append(part)
        for si, s in enumerate(sents):
            pieces = _hard_wrap(s)
            for i, piece in enumerate(pieces):
                end = si == len(sents) - 1 and i == len(pieces) - 1 and pi != len(paras) - 1
                out.append((piece, end))
    return out


def speakable(reply):
    """A chat reply as it should be read aloud: drop the parser name and list numbering noise."""
    return re.sub(r"\s*Parser: .*$", "", reply or "", flags=re.S).strip()
