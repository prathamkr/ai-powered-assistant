"""Fixes for what the built-in voice pack writes.

The built-in pack (Vosk, small Indian English model) has no Hindi words and no app names like
"WhatsApp" or "LinkedIn" in its vocabulary, so it writes similar-sounding English words instead:
"battery kidney" for "battery kitni hai", "open what's up" for "open whatsapp", "youtube galore"
for "youtube kholo". normalize() turns the common ones back, ONLY for text from that engine.

Each rule needs the words around it that a command has (an app name before "kholo", "battery"
before "kitni", "on"/"open" before "whatsapp"), so ordinary English is left alone. The misheard
forms were collected by running the model on Indian English voices (scratchpad eval, 2026-11-28).
"""
import re

_KARO = r"(?:karo|car\s+or|ca\s+or|car\s+oh|caro|crow|core)"
_APPS = r"(?:youtube|whatsapp|instagram|camera|settings|chrome|maps|gmail|spotify|snapchat|telegram|linkedin)"

RULES = [
    # filler the model hears before a command: "the open youtube", "uh call mummy"
    (r"^(?:the|uh|um|a|oh)\s+(?=(?:open|call|send|set|turn|play|show|make|add|remind)\b)", ""),
    # app names
    (r"\b(on|open|in|to|pe|par|oh)\s+(?:what'?s|whats|what)\s+up\b", r"\1 whatsapp"),
    (r"^oh\s+whatsapp$", "open whatsapp"),
    (r"\b(?:wife\s+i|why\s+fi(?:ve|re)?|why\s+fight|wi\s+fi|my\s+fi)\b", "wifi"),
    (r"\b(on|open|in|pe|par)\s+(?:linked\s+in|lint\s+din|link\s+din|linton|lincoln)\b", r"\1 linkedin"),
    (r"\b(on|open|in|pe|par)\s+(?:insta\s+gram|instead\s+gram)\b", r"\1 instagram"),
    # Hindi words
    (r"\bbattery\s+(?:kidney|kitney|kick\s+me)(?:\s+(?:heh|here|hey|high|hi|hay))?\b", "battery kitni hai"),
    (r"\b(?:kidney|kitney)\s+(?:heh|here|hey|hay)\b", "kitni hai"),
    (r"\b(%s)\s+(?:galore|hollow|holo|kolo|colo|cola|go\s+low)\s*$" % _APPS, r"\1 kholo"),
    (r"(^|\s)(?!(?:let'?s|i|we|you|please|and|to)\s)([\w']+)\s+(?:core|go|co|cow)\s+(?=(?:message|msg|sms|call|text)\b)",
     r"\1\2 ko "),
    (r"\b(message|msg|call|on|off|band|chalu|search|open)\s+%s\b" % _KARO, r"\1 karo"),
    (r"\b(on|off)\s+or\s*$", r"\1 karo"),
    (r"\b(?:car\s+or|ca\s+or|caro|crow)\s*$", "karo"),
    (r"\bkaro\s+(?:key|kee)\b", "karo ki"),
    # names
    (r"\bmum\s+me\b", "mummy"),
    (r"^call\s+(?:money|mommy)$", "call mummy"),
    (r"\bpa\s+pa\b", "papa"),
]
_COMPILED = [(re.compile(p), r) for p, r in RULES]


def normalize(text):
    """Text from the built-in voice pack -> text for the parser (lower case, fixes applied)."""
    t = " ".join((text or "").lower().split())
    for rx, rep in _COMPILED:
        t = rx.sub(rep, t)
    return " ".join(t.split())
