"""Settings > Customize: which messaging apps are on this phone, and what Lazey needs to send messages
through each of them. Pure Python (the phone checks are passed in as `state`), so it is tested on a PC.

    scan(packages, default_sms)   -> apps found on the phone, in display order
    requirements(app_id, state)   -> what is needed for that app, each with ok + how to fix it
"""
READ_CONTACTS = "android.permission.READ_CONTACTS"
SEND_SMS = "android.permission.SEND_SMS"

# id -> label, package names, how Lazey reaches it ("ready" support) or why not
CATALOG = [
    ("sms", "SMS", (), "supported"),   # the phone's default SMS app (found separately)
    ("whatsapp", "WhatsApp", ("com.whatsapp",), "supported"),
    ("whatsapp_business", "WhatsApp Business", ("com.whatsapp.w4b",), "supported"),
    ("instagram", "Instagram", ("com.instagram.android",), "supported"),
    ("messenger", "Messenger", ("com.facebook.orca",), "untested"),
    ("snapchat", "Snapchat", ("com.snapchat.android",), "untested"),
    ("facebook", "Facebook", ("com.facebook.katana",), "via_messenger"),
    ("telegram", "Telegram", ("org.telegram.messenger", "org.telegram.messenger.web"), "untested"),
    ("signal", "Signal", ("org.thoughtcrime.securesms",), "untested"),
    ("gmail", "Gmail", ("com.google.android.gm",), "supported"),   # email: compose opens typed, you press Send
    ("linkedin", "LinkedIn", ("com.linkedin.android",), "supported"),   # sent on the phone 2026-11-28
    ("x", "X (Twitter)", ("com.twitter.android",), "untested"),
    ("discord", "Discord", ("com.discord",), "untested"),
    ("google_chat", "Google Chat", ("com.google.android.apps.dynamite",), "untested"),
    ("teams", "Microsoft Teams", ("com.microsoft.teams",), "untested"),
    ("slack", "Slack", ("com.Slack",), "untested"),
    ("truecaller", "Truecaller", ("com.truecaller",), "supported"),   # its messages are SMS
]
LABEL = {i: l for i, l, _, _ in CATALOG}
SUPPORT = {i: s for i, _, _, s in CATALOG}
# reached by a saved username / id, through phone control (see pa/control.py SOCIAL)
SOCIAL = ("instagram", "messenger", "snapchat", "telegram", "signal", "linkedin", "x", "teams", "discord", "slack",
          "google_chat")
WHAT = {"signal": "phone number (+91...)", "teams": "work email", "gmail": "email"}
BY_NAME = ("linkedin", "discord", "slack", "google_chat")   # the chat is found by the person's name in the app's chat list
# why an app cannot be used (shown instead of "not supported yet")
REASON = {}
NOTE = {
    "linkedin": "Only people you already have a LinkedIn chat with (in your Messaging list) can be messaged.",
    "discord": "Only people already in your Discord DM list (near the top) can be messaged.",
    "truecaller": "Truecaller messages are SMS, so Lazey sends them as SMS.",
    "slack": "Lazey opens Slack and looks for the chat by name on the first screen (open DMs / recent chats).",
    "google_chat": "Lazey opens Google Chat and looks for the chat by name on the first screen.",
    "signal": "Save the person's number with country code, e.g. +919876543210.",
}
EMAIL_RE = r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,120}\.[A-Za-z]{2,24}"

EXAMPLE = {   # shown in Settings (English, like the rest of Settings)
    "sms": "send sms to rahul saying I am late",
    "whatsapp": "send hi to rahul on whatsapp",
    "whatsapp_business": "send hi to rahul on whatsapp",
    "instagram": "save rahul's instagram as rahul_23  ->  send hi to rahul on instagram",
    "messenger": "save rahul's messenger as rahul.sharma  ->  send hi to rahul on messenger",
    "snapchat": "save rahul's snapchat as rahul.snap  ->  send hi to rahul on snapchat",
    "gmail": "save rahul's email as rahul@gmail.com  ->  email rahul saying meeting at 5",
    "telegram": "save rahul's telegram as rahul_k23  ->  send hi to rahul on telegram",
    "signal": "save rahul's signal as +919876543210  ->  send hi to rahul on signal",
    "linkedin": "send hi to sarita sheoran on linkedin",
    "x": "save rahul's twitter as rahul  ->  send hi to rahul on twitter",
    "teams": "save rahul's teams as rahul@company.com  ->  send hi to rahul on microsoft teams",
    "discord": "send hi to rahul king on discord",
    "truecaller": "send sms to rahul saying I am late",
    "slack": "send hi to rahul sharma on slack",
    "google_chat": "send hi to rahul sharma on google chat",
}

# words people use for each app, for "how do I message on X?" (lower case, whole words)
WORDS = {
    "sms": r"sms|text message",
    "whatsapp": r"what'?s\s?app|wh?ats?app|whatsap|wa",
    "instagram": r"insta(?:gram)?|ig",
    "messenger": r"messenger|fb messenger|facebook messenger",
    "snapchat": r"snap(?:chat)?",
    "facebook": r"facebook|fb",
    "gmail": r"g\s?mail|e-?mail|mail",
    "telegram": r"telegram", "signal": r"signal", "linkedin": r"link(?:ed|d)\s?[il]n|linke?den|linke?dn|lnkd\s?in", "discord": r"discord",
    "x": r"twitter", "truecaller": r"true\s?caller", "teams": r"ms teams|microsoft teams",
    "slack": r"slack", "google_chat": r"google chat|gchat",
}


def scan(packages, default_sms=None):
    """[{id, label, package, support}] for the messaging apps installed (packages = installed package
    names). SMS is listed when the phone has a default SMS app."""
    installed = set(packages or ())
    out = []
    for app_id, label, pkgs, support in CATALOG:
        if app_id == "sms":
            if default_sms:
                out.append({"id": "sms", "label": label, "package": default_sms, "support": support})
            continue
        pkg = next((p for p in pkgs if p in installed), None)
        if pkg:
            out.append({"id": app_id, "label": label, "package": pkg, "support": support})
    return out


def not_installed(packages):
    """Apps Lazey can message with that are NOT on this phone (shown so they can be installed)."""
    installed = set(packages or ())
    out = []
    for app_id, label, pkgs, support in CATALOG:
        if app_id in ("sms", "facebook", "truecaller") or support == "unsupported" or not pkgs:
            continue
        if not any(p in installed for p in pkgs):
            out.append({"id": app_id, "label": label, "package": pkgs[0], "support": support, "missing": True})
    return out


def _req(rid, label, ok, fix=None, optional=False, note=""):
    return {"id": rid, "label": label, "ok": bool(ok), "fix": None if ok else fix, "optional": optional,
            "note": note}


def requirements(app_id, state):
    """What Lazey needs to send messages through app_id. state: {"perms": {perm: bool},
    "auto_send": bool, "phone_control": bool, "handles": {app_id: count}, "installed": set of app ids}."""
    perms = state.get("perms", {})
    contacts = _req("perm_contacts", "Permission to read contacts (to find a number by name)",
                    perms.get(READ_CONTACTS), fix="perm:" + READ_CONTACTS)
    if app_id in ("sms", "truecaller"):
        return [_req("perm_sms", "Permission to send SMS", perms.get(SEND_SMS), fix="perm:" + SEND_SMS), contacts]
    if app_id in ("whatsapp", "whatsapp_business"):
        return [contacts,
                _req("auto_send", "WhatsApp auto-send (Lazey presses Send; when off, you press Send)",
                     state.get("auto_send"), fix="auto_send", optional=True)]
    if app_id in BY_NAME:   # no username needed: the person's name is enough
        return [_req("phone_control", "Lazey phone control ON (to open the chat, type and press Send)",
                     state.get("phone_control"), fix="phone_control")]
    if app_id in SOCIAL:
        n = state.get("handles", {}).get(app_id, 0)
        return [_req("phone_control", "Lazey phone control ON (to open the chat, type and press Send)",
                     state.get("phone_control"), fix="phone_control"),
                _req("handles", "At least one saved %s (now %d)" % (WHAT.get(app_id, "username"), n), n > 0,
                     fix="handle_help:" + app_id,
                     note="Tell Lazey the %s of each person you want to message, once." % WHAT.get(app_id, "username"))]
    if app_id == "gmail":
        n = state.get("handles", {}).get("gmail", 0)
        return [_req("handles", "At least one saved email address (now %d)" % n, n > 0, fix="handle_help:gmail",
                     note="Tell Lazey the email address of each person you want to email, once. Gmail opens with "
                          "the email typed; you press Send.")]
    if app_id == "facebook":
        return [_req("messenger_app", "Messenger app installed (Facebook messages are sent with Messenger)",
                     "messenger" in state.get("installed", ()), fix="install:com.facebook.orca")]
    return []


def requirements_for(app, state):
    """requirements(), with "the app is installed" first for an app that is not on the phone."""
    reqs = requirements(app["id"], state)
    if app.get("missing"):
        reqs = [_req("installed", "%s app installed" % app["label"], False, fix="install:" + app["package"])] + reqs
    return reqs


def status(app, state):
    """('ready' | 'setup' | 'unsupported' | 'missing', number of required things still missing)."""
    if app["support"] == "unsupported":
        return "unsupported", 0
    if app.get("missing"):
        return "missing", 1
    missing = [r for r in requirements_for(app, state) if not r["ok"] and not r["optional"]]
    return ("ready" if not missing else "setup"), len(missing)


def status_text(app, state):
    st, n = status(app, state)
    if st == "unsupported":
        return "Not supported yet"
    if st == "missing":
        return "Not installed"
    extra = " (not tested on a phone)" if app["support"] == "untested" else ""
    return ("Ready" if st == "ready" else "Setup needed (%d)" % n) + extra


def how_to(app_id, apps, state):
    """Answer to "how do I message on <app>?" (Hinglish, like the chat): installed?, what is done / still
    needed, and how to ask. app_id None = which apps can be used."""
    found = {a["id"]: a for a in apps}
    if app_id is None:
        if not apps:
            return "Is phone par koi messaging app nahi mila."
        lines = ["- %s: %s" % (a["label"], status_text(a, state)) for a in apps]
        return "Is phone par ye messaging apps hain:\n" + "\n".join(lines) + \
            "\nKisi bhi app ke baare mein pucho, jaise 'instagram pe message kaise bheju'."
    label = LABEL.get(app_id, app_id)
    app = found.get(app_id)
    if app is None:
        return "%s is phone par install nahi hai." % label
    if app["support"] == "unsupported":
        return ("%s phone par hai, par Lazey %s se message nahi bhej sakta. %s" % (label, label, REASON.get(app_id, ""))).strip()
    out = ["%s se message bhejne ke liye:" % label]
    for r in requirements(app_id, state):
        out.append("%s %s%s" % ("[OK]" if r["ok"] else "[BAAKI]", r["label"], " (optional)" if r["optional"] else ""))
    st, n = status(app, state)
    out.append("Sab ready hai." if st == "ready" else "Baaki cheezein Settings > Customize > %s mein 'Fix this' se "
                                                    "theek karo." % label)
    if app_id in EXAMPLE:
        out.append("Aise bolo: " + EXAMPLE[app_id])
    if app_id in NOTE:
        out.append(NOTE[app_id])
    if app["support"] == "untested":
        out.append("(Ye flow asli phone par test nahi hua.)")
    return "\n".join(out)
