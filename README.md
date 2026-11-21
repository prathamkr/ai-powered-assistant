# Local Assistant: hackathon prototype

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
| Voice: speak a command (Mic button) | Phone: mic permission prompt, listening, silence -> "I did not hear anything", mic released. en-IN refused offline (error 13) on the test phone, app fell back automatically |
| Voice: replies read aloud (5 voice presets, pitch/speed) | Phone: speech playback confirmed in `dumpsys audio` (not judged by ear) |
| On-device LLM | **Not implemented** |
| Messages / Settings / Files adapters | **Unsupported** (never report success) |

Call (user's choice: **no Approve tap**): the call is placed immediately when exactly one
contact matches the name (+ optional first 3-6 digits of the number) and the requested SIM
(`sim 1`, `dusri sim`, `airtel se`) exists. Otherwise it asks (several matches) or refuses
(SIM not found, permission missing) and says "No call was made". Calls go through
`TelecomManager.placeCall` with the SIM's PhoneAccountHandle. Audit logs
`not_required:user_setting_direct_call`, never names or numbers.
Voice (ported from the `add-pocketmind-voice` branch, its "Android fallback" path, in Python):
**Mic** listens with the phone's own `SpeechRecognizer` (en-IN, so Hinglish comes out in Latin
letters), then sends the text like a typed message. Replies are read with the phone's
`TextToSpeech`, sentence by sentence. **Voice** button: speak replies (after voice / always / off),
Nova/Atlas/Echo/Luna/Spark presets, pitch, speed, prefer-offline. Recognizer order: on-device ->
phone recognizer offline -> phone recognizer online -> en-US -> phone language; the status line
says which one is used. The phone recognizer **may send audio to Google**; the app itself has no
INTERNET permission. Mic and speaker are never on together; both stop when the app is in the
background. Settings are stored in `voice.json` (no personal data). Lists can be answered by voice
("second one", "dusra wala"). The branch's sherpa-onnx offline engine was **not** ported
(English-only recognizer, +100 MB).
Photos: read-only, no approval needed; only photos from the latest search can be opened.
Contacts/call/photos permissions are requested the first time the feature is used.

Bugs found on the emulator and fixed: Keystore varargs call aborted the app (JNI
ArrayStoreException); permission callback touched UI off the main thread; calendar
`putExtra` overload TypeError; popups had no Close button.

Found on the phone and fixed: "Delete ALL my data" left deleted rows in SQLite free pages
(now `PRAGMA secure_delete=ON` + `VACUUM`; verified on phone: 0 traces left in the DB file);
chat did not auto-scroll after long lists; stale photo lists stayed tappable.

## Folder structure
    main.py                 Kivy UI (one screen)
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
    docs/FEASIBILITY.md

## Run tests (Windows / any OS)
    pip install cryptography pycryptodome
    python tests/test_pa.py

## Run UI on desktop
Desktop has no Android Keystore, so you must opt in to an **insecure** dev key:

    pip install kivy
    set PA_ALLOW_INSECURE_DEV_KEY=1
    python main.py

Calendar actions report "not available" on desktop (correct behaviour).

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
