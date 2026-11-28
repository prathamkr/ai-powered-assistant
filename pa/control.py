"""Phone control: step-by-step commands that Lazey performs inside other apps through the
"Lazey phone control" Accessibility service (java/org/pa/assistant/PhoneControlService.java).

This is NOT an LLM agent. The user says the steps; this module only turns their words into a
fixed list of simple operations, e.g.

    "youtube kholo phir lofi search karo"  -> [open youtube] [search "lofi"]
    "whatsapp kholo, rahul pe click karo, hi type karo"

Every plan is shown to the user and runs only after they tap Approve (pa/approval.py). The Java
service acts only while an approved plan is running and never touches password fields.
"""
import re

OPS = {"open", "click", "type", "enter", "search", "scroll", "back", "home", "recents",
       "notifications", "read", "wait", "open_url", "expect", "expect_sent", "pick"}  # open_url/expect: built by Lazey, never parsed

# Messaging apps that are reached by username (not phone number). The chat is opened with the app's
# own link IN THAT APP; before typing, the username must be on the screen ("expect").
SOCIAL = {
    # link: opens the chat (or the profile) IN that app. chat_id: the app's chat text box (a sure sign a
    # chat opened). marker: a label that must be on the profile before tapping. after_open: taps after it.
    "instagram": {"label": "Instagram", "package": "com.instagram.android", "link": "https://ig.me/m/%s",
                  "handle": r"[A-Za-z0-9._]{1,30}", "chat_id": "row_thread_composer_edittext"},
    "messenger": {"label": "Messenger", "package": "com.facebook.orca", "link": "https://m.me/%s",
                  "handle": r"[A-Za-z0-9.]{1,50}"},
    "snapchat": {"label": "Snapchat", "package": "com.snapchat.android", "link": "https://www.snapchat.com/add/%s",
                 "handle": r"[A-Za-z][A-Za-z0-9._-]{2,14}", "after_open": ("chat",)},
    "telegram": {"label": "Telegram", "package": "org.telegram.messenger", "link": "https://t.me/%s",
                 "handle": r"[A-Za-z][A-Za-z0-9_]{4,31}"},
    "signal": {"label": "Signal", "package": "org.thoughtcrime.securesms", "link": "https://signal.me/#p/%s",
               "handle": r"\+[1-9][0-9]{7,14}", "what": "phone number with country code (+91...)"},
    # LinkedIn / X: the profile opens; its "Message" button is there only for people you may message
    # (LinkedIn: your connections, seen on the phone: a non-connection shows Follow / Connect only)
    # LinkedIn: only people you already have a chat with can be messaged, so the chat is found BY NAME in
    # the Messaging list (rows: messaging_conversation_list_item_title, seen on the phone)
    "linkedin": {"label": "LinkedIn", "package": "com.linkedin.android", "by_name": True,
                 "inbox": "https://www.linkedin.com/messaging/", "pick_id": "messaging_conversation_list_item_title",
                 "handle": r"[^\x00-\x1f()]{1,60}"},
    "x": {"label": "X (Twitter)", "package": "com.twitter.android", "link": "https://x.com/%s",
          "handle": r"[A-Za-z0-9_]{1,15}", "marker": "message", "after_open": ("message",)},
    "teams": {"label": "Microsoft Teams", "package": "com.microsoft.teams",
              "link": "https://teams.microsoft.com/l/chat/0/0?users=%s",
              "handle": r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,120}\.[A-Za-z]{2,24}", "what": "work email address"},
    # Discord has no link to a person's DMs: open the app, Direct Messages, then that person's DM, which
    # the app labels "<display name> (direct message)" (seen on the phone). Only people already in the DM list.
    # Slack / Google Chat: no link opens a person's chat (it needs workspace / space IDs), so the app is
    # opened and the chat is picked by name from what is on the screen (NOT tested on a phone)
    "slack": {"label": "Slack", "package": "com.Slack", "open": "app", "by_name": True, "handle": r"[^\x00-\x1f()]{1,60}"},
    "google_chat": {"label": "Google Chat", "package": "com.google.android.apps.dynamite", "open": "app",
                    "by_name": True, "handle": r"[^\x00-\x1f()]{1,60}"},
    "discord": {"label": "Discord", "package": "com.discord", "open": "app", "by_name": True,
                "open_tap": "direct messages",
                "pick_suffix": " (direct message)", "handle": r"[^\x00-\x1f()]{1,60}"},
}
# LinkedIn as people type it: linkedin, linked in, linkedln (L for i), linkdin, linkden, linkedn
LINKEDIN_WORDS = r"link(?:ed|d)\s?[il]n|linke?den|linke?dn|lnkd\s?in"
# words that name these apps in a message ("rahul ko telegram pe hi bhejo"). "signal" is also a normal
# word ("signal nahi hai"), so it counts only as "on/via signal" or "signal pe/par/se".
SOCIAL_WORDS = (r"insta(?:gram)?|ig|snap(?:chat)?|fb\s+messenger|facebook\s+messenger|messenger|fb|facebook|"
                r"telegram|" + LINKEDIN_WORDS + r"|discord|twitter|ms\s+teams|microsoft\s+teams|slack|google\s+chat|gchat|"
                r"(?<=\bon\s)signal|(?<=\bvia\s)signal|signal(?=\s+(?:pe|par|se|me|mein|app)\b)")


# the same apps when SAVING a username ("rahul ka signal +91... hai"): here "signal" is always the app
HANDLE_WORDS = (r"insta(?:gram)?|ig|snap(?:chat)?|fb\s+messenger|facebook\s+messenger|messenger|fb|facebook|"
                r"telegram|" + LINKEDIN_WORDS + r"|discord|twitter|ms\s+teams|microsoft\s+teams|teams|signal|slack|google\s+chat|gchat")


def social_app(word):
    w = re.sub(r"\s+", " ", (word or "").lower().strip())
    if w.startswith(("insta", "ig")):
        return "instagram"
    if w.startswith("snap"):
        return "snapchat"
    if w in ("messenger", "fb", "facebook", "fb messenger", "facebook messenger"):
        return "messenger"
    if re.fullmatch(LINKEDIN_WORDS, w):
        return "linkedin"
    for start, app in (("telegram", "telegram"), ("signal", "signal"), ("discord", "discord"),
                       ("twitter", "x"), ("ms teams", "teams"), ("microsoft teams", "teams"), ("teams", "teams"),
                       ("slack", "slack"), ("google chat", "google_chat"), ("gchat", "google_chat")):
        if w.startswith(start):
            return app
    return None


def valid_handle(app, handle):
    return app in SOCIAL and bool(re.fullmatch(SOCIAL[app]["handle"], handle or ""))


def social_steps(app, handle, text):
    """Open the chat, check it is the right person, type, press Send, check the message is in the chat."""
    s = SOCIAL[app]
    if s.get("by_name"):   # LinkedIn, Discord: the chat is picked by name from the app's chat list
        if s.get("open") == "app":
            steps = [{"op": "open", "package": s["package"], "label": s["label"]}]
            if s.get("open_tap"):
                steps.append({"op": "click", "text": s["open_tap"]})
        else:
            steps = [{"op": "open_url", "url": s["inbox"], "package": s["package"], "label": s["label"], "handle": ""}]
        steps.append({"op": "pick", "text": handle, "id": s.get("pick_id", ""), "suffix": s.get("pick_suffix", "")})
    else:
        steps = [{"op": "open_url", "url": s["link"] % handle, "package": s["package"], "label": s["label"],
                  "handle": handle},
                 {"op": "expect", "text": s.get("marker") or handle, "chat_id": s.get("chat_id", "")}]
    steps += [{"op": "click", "text": t} for t in s.get("after_open", ())]
    steps += [{"op": "type", "text": text}, {"op": "click", "text": "send"}, {"op": "expect_sent", "text": text}]
    return steps


GLOBAL_OPS = {"home", "recents", "notifications"}  # work from any screen, no app needed
# Apps the service cannot work in. The test phone (vivo, Android 16) switches every downloaded
# Accessibility service OFF while its Settings app is on screen (seen with dumpsys accessibility).
BLOCKED_PACKAGES = {"com.android.settings"}
MAX_STEPS = 12
MAX_TEXT = 200
# A click on a button with one of these words changes something for real. The user must have
# said the word themselves ("send pe click karo"); the Java side checks the same.
RISKY = re.compile(r"\b(send|bhejo|pay|payment|buy|order|purchase|delete|remove|uninstall|install|"
                   r"confirm|submit|post|share|transfer|call|subscribe|unsubscribe|block|report|"
                   r"logout|log out|sign out|erase|reset|accept|allow)\b", re.I)

_SPLIT = re.compile(r"\s*(?:;|,|\band then\b|\bthen\b|\bphir se\b|\bphir\b|\bfir\b|\buske baad\b|"
                    r"\bafter that\b|\band\b|\baur\b)\s*", re.I)
_CMD = r"(?:karo|kar\s*do|kardo|kar|karna|karke|kijiye)"


def _q(s):
    """Strip quotes/spaces/punctuation around a target or text."""
    return s.strip().strip(" .!?\"'“”‘’").strip()


def split_parts(text):
    """Split on then/phir/aur/commas, but never inside quotes ('type "rock and roll"')."""
    keep = {}

    def hide(m):
        key = "\x00%d\x00" % len(keep)
        keep[key] = m.group(0)
        return key

    s = re.sub(r"\"[^\"]*\"|“[^”]*”|'[^']*'", hide, text)
    parts = [p for p in _SPLIT.split(s) if p and p.strip()]
    out = []
    for p in parts:
        for k, v in keep.items():
            p = p.replace(k, v)
        out.append(p.strip())
    return out


def parse_step(part, parse_open, photo_words):
    """One part -> one or two steps (an 'X me Y search karo' opens X then searches), or None."""
    low = part.lower().strip(" .!")
    if not low:
        return None
    if re.fullmatch(r"(?:go\s+back|back|press\s+back|back\s+(?:jao|karo|dabao|button\s+dabao)|"
                    r"(?:peeche|piche|pichhe|wapas|vapas)\s+(?:jao|chalo|aao))", low):
        return [{"op": "back"}]
    if re.fullmatch(r"(?:go\s+(?:to\s+)?home|home|home\s+screen|press\s+home|go\s+to\s+(?:the\s+)?home\s+screen|"
                    r"home\s+(?:jao|pe\s+jao|par\s+jao|screen\s+pe\s+jao|button\s+dabao))", low):
        return [{"op": "home"}]
    if re.fullmatch(r"(?:show\s+)?recents?(?:\s+apps)?|recent\s+apps\s+(?:dikhao|kholo)", low):
        return [{"op": "recents"}]
    if re.fullmatch(r"(?:show\s+|open\s+)?(?:the\s+)?notifications?(?:\s+panel)?|"
                    r"notifications?\s+(?:dikhao|kholo|dekho|batao)", low):
        return [{"op": "notifications"}]
    if re.fullmatch(r"(?:read\s+(?:the\s+|my\s+)?screen|what'?s\s+on\s+(?:the\s+|my\s+)?screen|"
                    r"what\s+is\s+on\s+(?:the\s+|my\s+)?screen|screen\s+(?:pe|par|per)\s+kya\s+(?:hai|likha\s+hai)|"
                    r"screen\s+padho|screen\s+padh\s+ke\s+batao|screen\s+read\s+%s)" % _CMD, low):
        return [{"op": "read"}]
    m = re.fullmatch(r"(?:wait|ruko|rukko|ruk\s+jao)(?:\s+(\d{1,2})\s*(?:sec|secs|seconds?|second))?|"
                     r"(\d{1,2})\s*(?:sec|secs|seconds?|second)\s+(?:wait|ruko)(?:\s+%s)?" % _CMD, low)
    if m:
        n = int(m.group(1) or m.group(2) or 2)
        return [{"op": "wait", "seconds": max(1, min(n, 15))}]
    m = re.fullmatch(r"(?:scroll\s+(down|up|neeche|niche|upar|uppar|ooper)|(neeche|niche|upar|uppar|ooper)\s+"
                     r"scroll(?:\s+%s)?|scroll(?:\s+%s)?|(neeche|niche|upar|uppar|ooper)\s+jao)" % (_CMD, _CMD), low)
    if m:
        d = (m.group(1) or m.group(2) or m.group(3) or "down")
        return [{"op": "scroll", "dir": "up" if d in ("up", "upar", "uppar", "ooper") else "down"}]
    if re.fullmatch(r"(?:press\s+)?enter(?:\s+(?:dabao|daba\s+do|press\s+%s|%s))?|(?:press\s+)?go\s+button" % (_CMD, _CMD),
                    low):
        return [{"op": "enter"}]
    # click (checked before search, so 'search pe click karo' taps the search button): "click on search", "tap send", "rahul pe click karo", "send button dabao"
    m = re.fullmatch(r"(?:click|tap|press|select|choose|touch)\s+(?:on\s+)?(?:the\s+)?(?P<t>.+?)(?:\s+button)?|"
                     r"(?P<t2>.+?)\s+(?:pe|par|per|on)\s+(?:click|tap|touch)(?:\s+%s)?|"
                     r"(?P<t3>.+?)\s+(?:button\s+)?(?:dabao|daba\s+do|dabana|press\s+%s)" % (_CMD, _CMD),
                     part.strip(" .!"), re.I)
    if m:
        t = _q(m.group("t") or m.group("t2") or m.group("t3"))
        if t and t.lower() not in ("enter", "back", "home"):
            return [{"op": "click", "text": t[:MAX_TEXT]}]
    # search: "youtube pe lofi search karo", "search lofi on youtube", "lofi search karo", "search for lofi"
    # ("find time / find 45 minutes / find a slot tomorrow ..." is planning, not a search)
    time_ask = re.match(r"(?:find|search\s+for)\s+(?:me\s+)?(?:some\s+|a\s+|free\s+)*(?:time|slot|\d+\s*(?:min|mins|minutes?|hours?))\b",
                        part.strip().lower())
    if not re.search(r"\b(%s)\b" % photo_words, low) and not time_ask:
        m = re.fullmatch(r"(?P<app>[\w .&'+-]+?)\s+(?:me|mein|main|pe|par|per)\s+(?P<q>.+?)\s+"
                         r"(?:search|dhundo|dhoondo|khojo|find)(?:\s+%s)?" % _CMD, part.strip(" .!"), re.I) or \
            re.fullmatch(r"(?:search|find|look\s+up)(?:\s+for)?\s+(?P<q>.+?)\s+(?:on|in)\s+(?P<app>[\w .&'+-]+?)",
                         part.strip(" .!"), re.I)
        if m and len(m.group("app").split()) <= 3:
            app = parse_open("open " + m.group("app").lower())
            if app:
                return [{"op": "open", "app": app}, {"op": "search", "text": _q(m.group("q"))[:MAX_TEXT]}]
        m = re.fullmatch(r"(?:search|find|look\s+up)(?:\s+for)?\s+(?P<q>.+)|(?P<q2>.+?)\s+"
                         r"(?:search|dhundo|dhoondo|khojo)(?:\s+%s)?" % _CMD, part.strip(" .!"), re.I)
        if m:
            q = _q(m.group("q") or m.group("q2"))
            if q:
                return [{"op": "search", "text": q[:MAX_TEXT]}]
    # type: "type hello", "hello type karo"
    m = re.fullmatch(r"(?:type|write)\s+(?P<t>.+)|(?P<t2>.+?)\s+type(?:\s+%s)?" % _CMD, part.strip(" .!"), re.I)
    if m:
        t = _q(m.group("t") or m.group("t2"))
        if t:
            return [{"op": "type", "text": t[:MAX_TEXT]}]
    app = parse_open(low)
    if app:
        return [{"op": "open", "app": app}]
    return None


def parse_control(text, parse_open, photo_words):
    """{'steps': [...]} when the WHOLE message is phone-control steps with at least one step that
    is not just opening an app; otherwise None (so 'open whatsapp' stays a plain app open)."""
    parts = split_parts(text)
    if not parts:
        return None
    steps = []
    for p in parts:
        st = parse_step(p, parse_open, photo_words)
        if st is None:
            return None
        steps.extend(st)
    if not steps or all(s["op"] == "open" for s in steps) or len(steps) > MAX_STEPS:
        return None
    return {"steps": steps}


def validate_steps(steps):
    """List of error strings (empty = OK). Steps come from the parser or a stored proposal."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        return ["1 to %d steps" % MAX_STEPS]
    errs = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or s.get("op") not in OPS:
            errs.append("step %d: unknown" % (i + 1))
            continue
        op = s["op"]
        if op == "open" and not re.fullmatch(r"[A-Za-z][\w.]{2,150}", str(s.get("package", ""))):
            errs.append("step %d: no app package" % (i + 1))
        if op in ("click", "type", "search"):
            t = s.get("text")
            if not isinstance(t, str) or not t.strip() or len(t) > MAX_TEXT or re.search(r"[\x00-\x1f]", t):
                errs.append("step %d: bad text" % (i + 1))
        if op == "scroll" and s.get("dir") not in ("up", "down"):
            errs.append("step %d: bad direction" % (i + 1))
        if op == "wait" and not (isinstance(s.get("seconds"), int) and 1 <= s["seconds"] <= 15):
            errs.append("step %d: bad wait" % (i + 1))
        if op == "open_url":
            app = next((k for k, v in SOCIAL.items() if v["package"] == s.get("package")), None)
            h = str(s.get("handle", ""))
            if not app or (s.get("url") != SOCIAL[app].get("inbox") if SOCIAL[app].get("by_name") else
                           (not valid_handle(app, h) or s.get("url") != SOCIAL[app]["link"] % h)):
                errs.append("step %d: bad chat link" % (i + 1))
        if op == "pick" and (not re.fullmatch(r"[^\x00-\x1f]{1,60}", str(s.get("text", "")))
                             or not re.fullmatch(r"[a-z_]{0,60}", str(s.get("id", "")))
                             or not re.fullmatch(r"[^\x00-\x1f]{0,40}", str(s.get("suffix", "")))):
            errs.append("step %d: bad chat name" % (i + 1))
        if op == "expect" and (not re.fullmatch(r"[^\x00-\x1f]{1,120}", str(s.get("text", "")))
                               or not re.fullmatch(r"[a-z_]{0,60}", str(s.get("chat_id", "")))):
            errs.append("step %d: bad check" % (i + 1))
        if op == "expect_sent" and (not isinstance(s.get("text"), str) or not s["text"].strip()
                                    or len(s["text"]) > MAX_TEXT):
            errs.append("step %d: bad check" % (i + 1))
    return errs


def describe(step):
    op = step["op"]
    if op == "open":
        return "Open %s" % (step.get("label") or step.get("app") or step.get("package"))
    if op == "open_url":
        if not step.get("handle"):
            return "Open %s messages" % step.get("label")
        return "Open the %s chat with @%s" % (step.get("label"), step.get("handle"))
    if op == "pick":
        return 'Open the chat with "%s" (asks you if several chats match)' % step["text"]
    if op == "expect":
        return 'Check the chat is with "@%s" (stops here if not)' % step["text"]
    if op == "expect_sent":
        return "Check the message shows in the chat"
    if op == "click":
        risky = " (this button does something for real)" if RISKY.search(step["text"]) else ""
        return 'Tap "%s"%s' % (step["text"], risky)
    if op == "type":
        return 'Type "%s"' % step["text"]
    if op == "search":
        return 'Search for "%s"' % step["text"]
    if op == "scroll":
        return "Scroll %s" % step["dir"]
    if op == "wait":
        return "Wait %d seconds" % step["seconds"]
    return {"enter": "Press Enter", "back": "Go back", "home": "Go to the home screen",
            "recents": "Show recent apps", "notifications": "Open notifications",
            "read": "Read the screen and tell you what is on it"}[op]


def preview(steps):
    return "Phone control, %d step%s:\n%s" % (
        len(steps), "" if len(steps) == 1 else "s", "\n".join("%d. %s" % (i + 1, describe(s)) for i, s in enumerate(steps)))
