# Lazey: hackathon prototype

Local-first Android assistant: Kivy UI, Python core, encrypted SQLite, approval-gated device actions.
**Prototype, not production-ready.** See `docs/FEASIBILITY.md` for risks and status labels.

Target: Android 10+ (API 29), arm64, 6 GB RAM. Hardware knobs live in `pa/config.py`.

## Status
"Emulator" = Android 11 x86_64 emulator running a TEST-ONLY x86_64 build of the same code.
The arm64 APK crashes on that emulator inside its ARM translator (`libndk_translation`,
SIGILL), so it was tested on a **real phone instead: vivo/iQOO (Android 16, arm64, ~6 GB RAM)**.
On the phone all 7 acceptance steps passed. Calendar form opened pre-filled with the right date,
time and IST timezone (discarded, not saved); the DB had no plaintext; delete-all worked.

| Component | Status |
|---|---|
| Preferences, notes, in-app tasks (encrypted SQLite) | Unit-tested on PC; works on emulator, survives restart |
| Note retrieval (lexical hashed vectors, **not neural**) | Unit-tested; works on emulator (unrelated note not returned) |
| Hinglish/English understanding | Constrained rule parser, **not an LLM** |
| Planner (slots, overlaps, missing details) | Unit-tested; on emulator avoids an existing task |
| Approval gate (payload hash, once-only) | Unit-tested; on emulator a double tap on Approve opens calendar once |
| Calendar: open system "new event" screen (user taps Save) | Emulator: Google Calendar opens. Event form not reached: it needs a Google account |
| Calendar: read availability (READ_CALENDAR) | Emulator: allow and deny paths both work (no events existed to collide with) |
| Android Keystore key wrapping | Emulator: key created, reused after restart; DB has no plaintext note text |
| Kivy UI | Emulator: all screens used (chat, proposal card, Prefs, Tasks, delete-all) |
| Call ("rahul 9876 ko sim 2 se call karo") | Unit-tested; phone: contacts lookup, number-prefix filter, SIM list with carrier name, wrong/empty SIM refused. A real call was **not** placed during testing |
| Photo search ("kal ki photos", "pichle hafte ke screenshots") | Unit-tested; phone: permission deny/allow, correct date ranges, Open hands off to system viewer |
| On-device LLM | **Not implemented** |
| Messages / Settings / Files adapters | **Unsupported** (never report success) |

Call (user's choice: **no Approve tap**): the call is placed immediately when exactly one
contact matches the name (+ optional first 3-6 digits of the number) and the requested SIM
(`sim 1`, `dusri sim`, `airtel se`) exists. Otherwise it asks (several matches) or refuses
(SIM not found, permission missing) and says "No call was made". Calls go through
`TelecomManager.placeCall` with the SIM's PhoneAccountHandle. Audit logs
`not_required:user_setting_direct_call`, never names or numbers.
Photos: read-only, no approval needed; only photos from the latest search can be opened.
Contacts/call/photos permissions are requested the first time the feature is used.

Bugs found on the emulator and fixed: Keystore varargs call aborted the app (JNI
ArrayStoreException); permission callback touched UI off the main thread; calendar
`putExtra` overload TypeError; popups had no Close button.

Found on the phone and fixed: "Delete ALL my data" left deleted rows in SQLite free pages
(now `PRAGMA secure_delete=ON` + `VACUUM`; verified on phone: 0 traces left in the DB file);
chat did not auto-scroll after long lists; stale photo lists stayed tappable.

## Folder structure
    main.py                 Kivy app (one screen): chat, proposal card, pop-ups
    pa_ui/                  Lazey look + customisation (see "Look and customisation")
      themes.py             8 themes, 9 backgrounds, contrast checks
      config.py             saved GUI settings (theme, layout, button placement)
      iconset.py            vector icons (no font or emoji needed)
      calendar_logic.py     month grid + task grouping
      widgets.py chrome.py lazey_widgets.py editor.py calendar_view.py   Kivy parts
    buildozer.spec          APK build config
    pa/
      bootstrap.py          wires key -> crypto -> store -> assistant
      assistant.py          orchestrator
      inference.py          backend interface, constrained parser, validation
      planner.py            deterministic slot finding
      approval.py           approval engine (hash-bound, idempotent)
      storage.py            SQLite + per-field AES-GCM + audit log
      crypto.py             AES-256-GCM (cryptography or pycryptodome)
      keys.py               Android Keystore / dev-only key providers
      embed.py              lexical vectors
      config.py             limits and windows
      adapters/base.py      adapter interface + UnsupportedAdapter
      adapters/calendar.py  Android calendar adapter
    tests/test_pa.py        unit + acceptance tests (mocks marked TEST-ONLY)
    tests/test_ui_config.py themes, backgrounds, config, calendar tests (no window needed)
    docs/FEASIBILITY.md

## Run tests (Windows / any OS)
    pip install cryptography pycryptodome
    python -m unittest discover -s tests

## Run UI on desktop
Desktop has no Android Keystore, so you must opt in to an **insecure** dev key:

    pip install kivy
    set PA_ALLOW_INSECURE_DEV_KEY=1
    python main.py

Calendar actions report "not available" on desktop (correct behaviour).

## Look and customisation
The screen is a dark, glowing design: wave logo and **Lazey** title with a tagline pill, a menu
button (top corner), a status avatar (tap it to see what the assistant is doing; the dot is green when ready,
amber when busy, red on an error), a greeting with an animated orb while the chat is empty, chat bubbles,
and a rounded typing bar (`+` quick prompts, text box, mic, send).

- **Menu button**: Theme, Calendar, Preferences, Voice. Calendar shows a month grid with dots on days that
  have tasks and the day's agenda (tasks can be deleted there; "Open phone calendar" works on Android only).
- **Theme** (menu > Theme), changes apply live and are saved on the phone:
  - *Themes*: Violet (default), Ocean, Emerald, Rose, Amber, Graphite, Daylight (light), High contrast, plus your own.
  - *Background colour*: 9 backdrops for the dark themes (Deep violet, Midnight blue, AMOLED black, Graphite,
    Forest night, Wine, Deep teal, Slate, Ember) or the theme's own.
  - *Colours*: every colour can be edited (hex or colour wheel) with a contrast warning.
  - *Layout*: quick layouts (Lazey, Minimal, Big touch, Left-handed, Typing bar on top), title alignment,
    menu side, typing bar position, greeting on/off, bubbles or plain text, sliders for sizes.
  - *Buttons*: for every button choose its icon and name, move it earlier/later, and put it in the Menu,
    before/after the text box, or hide it. The Theme entry can never be hidden.
- Settings live in `ui_config.json` in the app's private folder; a damaged file is kept as `.bad` and
  defaults are used. Colour changes never touch the assistant core (`pa/`).
- Mic and Voice call optional hooks (`app.voice_input`, `app.voice_settings`); without them they say
  "not connected in this build". This repo has no speech engine.
- Fonts (in `pa_ui/fonts/`, SIL Open Font Licence, licences included): **Poppins SemiBold 600** for the app name,
  headings and greeting; **Poppins Regular 400** for subtitles and descriptions; **Inter Regular 400** for the
  message box, chat and smaller UI text. Inter is the default for every widget (`pa_ui/fonts.py`).
- Renaming note: the APK package is now `org.pa.lazey` (was `org.pa.localassistant`), so it installs as a
  new app and does not share the old app's encrypted data.

## Build APK (WSL2 Ubuntu)
    sudo apt install -y python3-venv git zip unzip openjdk-17-jdk build-essential \
      autoconf automake libtool pkg-config cmake libffi-dev libssl-dev zlib1g-dev libltdl-dev
    python3 -m venv ~/venv && ~/venv/bin/pip install buildozer cython setuptools
    cp -r /mnt/c/ai ~/pa && cd ~/pa      # build on the Linux filesystem, not /mnt/c
    ~/venv/bin/buildozer android debug   # output: bin/*.apk

Install: copy the APK to the phone, allow "Install unknown apps", install, open.
No model or dependency is downloaded at runtime.

## More commands
- `rahul ko call karo` / `mummy ko phone lagao` / `call 9876543210`
- `rahul 9876 ko sim 2 se call karo` / `rahul ko airtel se call karo` / `dusri sim se mummy ko call karo`
- `call neha whose number starts with 7012 from sim 1` / `can you call mummy from second sim` / `call rahul via airtel`
- If the full name matches no contact, each word is tried alone; such partial matches always
  show a list to choose from and are **never** dialled directly.
- `kal ki photos dikhao` / `aaj ki photos` / `pichle hafte ke screenshots dikhao` / `camera ki photos`

## Demo checklist (acceptance scenario)
1. `Yaad rakho mujhe subah kaam karna pasand hai.` -> "Preference saved"
2. `Note karo: project report mein budget section add karna hai` -> "Note saved"
3. `Project report ke baare mein maine kya note kiya tha?` -> shows the note
4. `Kal project par 45 minutes kaam karne ka time nikalo.` -> proposal card with exact time
5. Tap **Approve** -> system calendar screen opens; message says event exists only after you tap Save
6. Close and reopen app -> **Prefs** and **Tasks** still show the data
7. Deny calendar permission / tap **Reject** -> no change; app says availability not checked

## Known limitations
- Parser understands only the documented phrasings; it is not an LLM.
- Retrieval matches words/spellings, not meaning.
- Calendar event creation needs the user to tap Save in the calendar app.
- No reminders/notifications.
- Decrypted text exists in RAM while in use; audit log is plaintext but content-free.
- APK size, RAM use and latency have not been measured.
