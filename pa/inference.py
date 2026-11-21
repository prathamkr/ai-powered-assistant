"""Inference interface + a constrained rule-based parser (NOT an LLM).
Backend output is untrusted: `validate` re-checks everything in application code."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config

ALLOWED = {"remember_preference", "add_note", "query_notes", "schedule_work",
           "call_contact", "find_photos", "send_message", "change_setting", "unknown"}
UNSUPPORTED = {"send_message", "change_setting"}
PHOTO_RANGES = {"today", "yesterday", "week", "month"}
# call_contact is NOT here: the user chose immediate calls when exactly one contact matches
# (see Assistant._call for the conditions that still force a question).
APPROVAL_INTENTS = {"schedule_work"}
CARRIERS = {"jio", "airtel", "vi", "vodafone", "idea", "bsnl"}
FIELDS = {
    "remember_preference": {"text"},
    "add_note": {"text"},
    "query_notes": {"query"},
    "schedule_work": {"title", "date", "time", "window", "duration_minutes"},
    "call_contact": {"name", "number", "prefix", "sim"},
    "find_photos": {"range", "keyword"},
}
CALL_FILLERS = set("ko to please plz karo kar do de dena lagao laga call dial phone fone ek zara jara "
                   "kardo krdo mujhe se baat karni hai karwa karwao make a the abhi sim wale wali wala "
                   "number no jiska jiske jo starting start shuru hota hoti from using via "
                   "usko unko isko inko use unhe inhe usse unse "
                   # English glue words ("call neha whose number starts with 7012 from sim 1")
                   "whose who which that his her their its starts started starting begins begin "
                   "beginning with digits digit and for me my can could you u pls kindly on in is "
                   "ka ki ke hai h hota hoti wo woh uska uski unka unki".split())
# "whose number starts with 7012", "number starting 7012", "jiska number 7012 se shuru hota hai"
PREFIX_PHRASE = re.compile(
    r"\b(?:(?:whose|jiska|jiske|jinka|uska|unka)\s+)?(?:(?:phone|mobile)\s+)?(?:number|no\.?|num)?\s*(?:is\s+)?"
    r"(?:starts?|starting|begins?|beginning|shuru)\s*(?:hota\s+|hoti\s+)?(?:from|with|by|se|at)?\s*"
    r"((?:\d[\s\-]?){3,6})(?!\d)")


def _parse_call(t, low):
    """Entities for a call request: name, number (full), prefix (first digits), sim."""
    ent, rest = {}, low
    m = (re.search(r"\bsim\s*(?:no\.?\s*|number\s*)?([12])\b", rest)
         or re.search(r"\b([12])\s*(?:no\.?|number)?\s*(?:wali|wale|vala|wala)?\s*sim\b", rest))
    if m:
        ent["sim"] = m.group(1)
    else:
        m = re.search(r"\b(pehli|pahli|pehle|first|1st|dusri|doosri|dusre|second|2nd)\s+(?:wali\s+)?sim\b", rest)
        if m:
            ent["sim"] = "1" if m.group(1) in ("pehli", "pahli", "pehle", "first", "1st") else "2"
        else:
            m = re.search(r"\b(%s)\s+(?:(?:wali|wale|ki|ke)\s+)?(?:sim\s+)?(?:se|from|using|via)\b"
                          % "|".join(CARRIERS), rest)
            if not m:  # English order: "via airtel", "from jio sim", "using vi"
                m = re.search(r"\b(?:from|using|via|through|on|with)\s+(?:my\s+|the\s+)?(%s)\b(?:\s+sim\b)?"
                              % "|".join(CARRIERS), rest)
            if m:
                ent["sim"] = m.group(1)
    if m:
        rest = rest[:m.start()] + " " + rest[m.end():]
    p = PREFIX_PHRASE.search(rest)
    if p:
        ent["prefix"] = re.sub(r"\D", "", p.group(1))
        rest = rest[:p.start()] + " " + rest[p.end():]
    # Walk the words. A 1-2 digit number right after a name word belongs to the name
    # ("neha 2" is a contact called "Neha 2"), unless more digits follow
    # ("rahul 98 11 ..." is a spaced phone number: another short group follows).
    # "neha 2 7012" = name "neha 2" + prefix 7012. Other digits form the number/prefix.
    toks = re.findall(r"\+?\d+|[^\W\d_][\w.]*", rest)
    name, digs = [], []
    for i, tk in enumerate(toks):
        if tk[0] in "+0123456789":
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            more = nxt[:1] in tuple("+0123456789") and len(nxt) <= 2 if nxt else False
            if len(tk) <= 2 and name and i and toks[i - 1] == name[-1] and not more:
                name.append(tk)
            else:
                digs.append(tk)
        elif tk not in CALL_FILLERS:
            name.append(tk)
    digits = "" if p else re.sub(r"\D", "", "".join(digs))
    if len(digits) >= 7:
        ent["number"] = "".join(digs)
    elif 3 <= len(digits) <= 6:
        ent["prefix"] = digits
    ent["name"] = " ".join(name)
    return ent
PHOTO_WORDS = r"photos?|pics?|pictures?|tasveer|tasvir|images?|gallery|screenshots?"
PHOTO_SKIP = set("ki ke wali wale of mere meri my aaj kal today yesterday pichle pichhle last is this "
                 "hafte week mahine month sab all saari saare dikhao dikha show find dhundo dhoondo "
                 "kholo open".split())
REQUIRED = {
    "remember_preference": ["text"], "add_note": ["text"], "query_notes": ["query"],
    "schedule_work": ["title", "duration_minutes", "date"],
}


class ModelUnavailable(Exception):
    pass


@dataclass
class Intent:
    intent: str
    entities: dict = field(default_factory=dict)
    missing_fields: list = field(default_factory=list)
    requires_approval: bool = False


class InferenceBackend:
    name = "base"
    is_llm = False

    def parse(self, text: str, today: date) -> dict:
        raise NotImplementedError


def _window_word(low):
    if re.search(r"\b(subah|morning)\b", low):
        return "morning"
    if re.search(r"\b(dopahar|afternoon)\b", low):
        return "afternoon"
    if re.search(r"\b(shaam|sham|evening)\b", low):
        return "evening"
    return None


def _time(low):
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", low)
    return "%02d:%s" % (int(m.group(1)), m.group(2)) if m else None


class ConstrainedParser(InferenceBackend):
    """Fixed patterns for English + Romanized Hindi. Only understands the phrasings below."""
    name = "constrained rule parser (NOT an LLM)"
    is_llm = False

    def followup(self, text):
        """Answer to 'which time?' question."""
        return {k: v for k, v in (("window", _window_word(text.lower())), ("time", _time(text.lower()))) if v}

    def parse(self, text, today):
        t = text.strip()
        low = t.lower()
        m = re.match(r"^(?:yaad rakho|yad rakho|remember(?: that)?)[\s,:\-]*(.+)$", low, re.S)
        if m:
            return {"intent": "remember_preference", "entities": {"text": t[m.start(1):]}}
        m = re.match(r"^note\s*(?:karo|kar do|kardo|this)?\s*[:\-]\s*(.+)$", low, re.S)
        if m:
            return {"intent": "add_note", "entities": {"text": t[m.start(1):]}}

        dur = re.search(r"(\d+)\s*(minutes?|mins?|min|ghante|ghanta|hours?|hrs?|hr)\b", low)
        if dur and re.search(r"\b(kaam|work|schedule|slot|time nikalo|time nikal|plan)\b", low):
            n = int(dur.group(1))
            if dur.group(2).startswith(("g", "h")):
                n *= 60
            ent = {"duration_minutes": n}
            if re.search(r"\b(kal|tomorrow)\b", low):
                ent["date"] = (today + timedelta(days=1)).isoformat()
            elif re.search(r"\bparso\b", low):
                ent["date"] = (today + timedelta(days=2)).isoformat()
            elif re.search(r"\b(aaj|today)\b", low):
                ent["date"] = today.isoformat()
            else:
                iso = re.search(r"\d{4}-\d{2}-\d{2}", low)
                if iso:
                    ent["date"] = iso.group(0)
            tm = re.search(r"^(?:(?:kal|aaj|parso|tomorrow|today)\s+)?(.+?)\s+(?:par|pe)\s+\d", t, re.I) or \
                re.search(r"work on (.+?)(?:\s+for\b|\s+tomorrow\b|\s+today\b|$)", t, re.I)
            if tm:
                ent["title"] = tm.group(1)
            ent.update(self.followup(t))
            return {"intent": "schedule_work", "entities": ent}

        if re.search(r"\bnote\b", low) and re.search(r"\b(kya|what|dikhao|show)\b", low):
            m = re.match(r"^(.+?)\s+(?:ke\s+baa?re\s+(?:mein|me)|about)\b", low)
            return {"intent": "query_notes", "entities": {"query": m.group(1) if m else low}}
        if re.search(r"\b(call|dial|phone|fone)\b", low) and not re.search(r"\b(%s)\b" % PHOTO_WORDS, low):
            return {"intent": "call_contact", "entities": _parse_call(t, low)}
        if re.search(r"\b(%s)\b" % PHOTO_WORDS, low):
            ent = {}
            if re.search(r"\b(aaj|today)\b", low):
                ent["range"] = "today"
            elif re.search(r"\b(kal|yesterday)\b", low):  # photos are in the past: kal = yesterday
                ent["range"] = "yesterday"
            elif re.search(r"(pichle|pichhle|last|is|this)\s+(hafte|week)", low):
                ent["range"] = "week"
            elif re.search(r"(pichle|pichhle|last|is|this)\s+(mahine|month)", low):
                ent["range"] = "month"
            if re.search(r"\bscreenshots?\b", low):
                ent["keyword"] = "screenshot"
            elif re.search(r"\bcamera\b", low):
                ent["keyword"] = "camera"
            elif re.search(r"\bwhatsapp\b", low):
                ent["keyword"] = "whatsapp"
            else:
                for pat in (r"([a-z0-9]+)\s+(?:ki|ke|wali|wale)\s+(?:%s)" % PHOTO_WORDS,
                            r"(?:%s)\s+(?:of|from)\s+([a-z0-9]+)" % PHOTO_WORDS):
                    km = re.search(pat, low)
                    if km and km.group(1) not in PHOTO_SKIP:
                        ent["keyword"] = km.group(1)
                        break
            return {"intent": "find_photos", "entities": ent}
        if re.search(r"\b(message|sms|whatsapp)\b", low):
            return {"intent": "send_message", "entities": {}}
        if re.search(r"\b(wifi|wi-fi|bluetooth|brightness|volume|airplane|torch)\b", low):
            return {"intent": "change_setting", "entities": {}}
        return {"intent": "unknown", "entities": {}}


def _clean(s, limit):
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(s)).strip()
    return s[:limit]


def validate(raw, today: date) -> Intent:
    """Treat backend output as untrusted. Missing fields and approval need are computed HERE."""
    if not isinstance(raw, dict) or raw.get("intent") not in ALLOWED:
        return Intent("unknown")
    name = raw["intent"]
    src = raw.get("entities") if isinstance(raw.get("entities"), dict) else {}
    ent = {}
    for k in FIELDS.get(name, ()):
        v = src.get(k)
        if v in (None, ""):
            continue
        try:
            if k in ("text", "query"):
                v = _clean(v, config.MAX_INPUT_CHARS)
            elif k == "title":
                v = _clean(v, config.MAX_TITLE_CHARS)
            elif k == "date":
                d = date.fromisoformat(str(v))
                if not (today - timedelta(days=1) <= d <= today + timedelta(days=366)):
                    continue
                v = d.isoformat()
            elif k == "time":
                v = datetime.strptime(str(v), "%H:%M").strftime("%H:%M")
            elif k == "window":
                if v not in config.WINDOWS:
                    continue
            elif k == "duration_minutes":
                v = int(v)
                if not 5 <= v <= 480:
                    continue
            elif k == "name":
                v = re.sub(r"[^\w .'-]", "", _clean(v, 60)).strip()
            elif k == "number":
                v = _clean(v, 25)
                if not re.match(r"^\+?[0-9][0-9 ()\-]{2,19}$", v) or len(re.sub(r"\D", "", v)) < 3:
                    continue
            elif k == "prefix":
                v = str(v)
                if not re.match(r"^\d{3,6}$", v):
                    continue
            elif k == "sim":
                v = str(v).lower()
                if v not in ("1", "2") and v not in CARRIERS:
                    continue
            elif k == "range":
                if v not in PHOTO_RANGES:
                    continue
            elif k == "keyword":
                v = _clean(v, 40).lower()
                if not re.match(r"^[\w ]{1,40}$", v):
                    continue
        except (ValueError, TypeError):
            continue
        if v != "":
            ent[k] = v
    missing = [f for f in REQUIRED.get(name, []) if f not in ent]
    if name == "call_contact":
        if ent.get("number"):
            ent.pop("prefix", None)  # a full number makes the prefix meaningless
        if not (ent.get("name") or ent.get("number")):
            missing.append("name")
    return Intent(name, ent, missing, requires_approval=(name in APPROVAL_INTENTS))


def load_backend(model_path=None):
    """No LLM is bundled. If a model path is given but unusable, say so; never go remote."""
    if model_path:
        raise ModelUnavailable("LLM backend not implemented/provisioned; using constrained parser.")
    return ConstrainedParser()
