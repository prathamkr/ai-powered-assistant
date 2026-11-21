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
| Open apps ("open whatsapp", "youtube kholo") | Unit-tested; phone: Calculator and WhatsApp opened (checked with `dumpsys window`), unknown app refused |
| Daily messages ("har subah 8 baje mummy ko good morning bhejo") | Unit-tested; phone (WhatsApp to a fake number): alarm set exactly, notification shown at the time **with the app process killed**, next day's alarm set. vivo removed that next alarm when it froze the app (`Reason=frozen`) until the app was battery-exempt; the app now asks for it. SMS sending **not** tested on the phone (it would send a real SMS) |
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
Nova/Atlas/Echo/Luna/Spark presets, pitch, speed. **Offline only** (default on): only the
on-device recognizer (`createOnDeviceSpeechRecognizer`, Android 13+) is used, so audio never
leaves the phone. Voice settings show which offline packs are installed
(`checkRecognitionSupport`) and can download one (`triggerModelDownload`, internet once).
Test phone: en-US was installed (mic worked offline), en-IN offered for download. With offline
only switched off: on-device -> phone recognizer -> en-US -> phone language, and the phone
recognizer **may send audio to Google**. The app itself has no INTERNET permission. Mic and speaker are never on together; both stop when the app is in the
background. Settings are stored in `voice.json` (no personal data). Lists can be answered by voice
("second one", "dusra wala"). The branch's sherpa-onnx offline engine was **not** ported
(English-only recognizer, +100 MB).
Everyday assistant (all offline; see docs/THIRD_PARTY.md for what came from which repository):
- Phone status (ported from PokeClaw's GetDeviceInfoTool, Apache-2.0): `battery kitni hai`,
  `storage kitna bacha hai`, `ram kitni free hai`, `agla alarm kab hai`, `phone details batao`,
  `is internet working?`, `what time is it`; with advice (low battery, hot battery, full storage).
- To-dos and reminders (shape from PokeClaw's kb_add_todo): `todo: buy milk`,
  `add todo pay bill tomorrow high priority`, `mujhe kal 5 baje yaad dilana ki bill bharna hai`,
  `remind me at 6 pm to drink water`, `show my todos`, `todo 2 done`, `mark buy milk done`.
  Timed reminders are one-time phone alarms + notification, even when the app is closed.
  Verified on the phone: a 7:10 PM reminder showed its notification at 7:10 and removed itself.
- Daily plan / decision support (own code): `aaj ka plan kya hai`, `plan my day`,
  `what should I do now`, `kal ka plan` -> calendar busy times, tasks, daily messages, to-dos
  (overdue first, then priority), next alarm, battery advice and a suggested free 30-minute slot
  for the most urgent to-do (uses the saved time-of-day preference).
- Routines (PokeClaw "skills" idea): `routine good morning: set an alarm for 7 am; battery kitni hai
  then open whatsapp`, run with `good morning` / `good morning routine` / Run button in Tasks.
- Timed routines: `good morning routine har din 7 baje`, `good morning routine weekdays subah 7 baje
  chalao`, `stop good morning routine`. At the time a notification "Routine: X" appears (even with
  the app closed); tapping it opens a screen-less activity (`RoutineTapActivity`) that notes the
  routine and opens the app, which runs it. Verified on the phone: notification at the set time
  with the app process killed; next day's alarm kept (only with the battery exemption).
- Weekly repeats: `har monday subah 9 baje rahul ko hi bhejo`, `every weekday at 8 am ...`,
  `weekend pe subah 10 baje ...` (daily messages and routines; monthly/hourly is refused).
- "Did you mean": unknown sentences get the 3 closest example commands.
- vivo (and similar) freeze background apps and DELETE their pending alarms ("Reason=frozen" in
  `dumpsys alarm`, seen several times). All timed features therefore ask for "allow background"
  (battery optimisation exemption) after they are set.
- Several commands in one line (PokeClaw router idea): `set an alarm for 6 and open youtube`;
  split only when every part is a known command; a second app is not opened over the first.
- Context: `usko phir se call karo` / `send her hi` = the person from the last call or message.
Alarms & timers (phone's Clock app, `AlarmClock` intents, SET_ALARM permission, no approval: the
user can change/delete it in Clock): `set an alarm of 5 am`, `subah 5 baje ka alarm lagao`,
`wake me up at 6:30`, `har din 6 baje ka alarm`, `alarm every monday at 7 am`,
`set an alarm at 6 am for gym`, `10 minute ka timer lagao`, `show my alarms`. Verified on the phone:
"set an alarm of 5 am" -> next alarm "Sun 5:00 AM" in the system.
Chat history: every chat line is stored encrypted (kind `chat`), the last 100 come back when the
app opens, the newest 500 are kept; "Clear chat history" in Prefs, also wiped by Delete ALL.
Message now: `send neha a message hi`, `open whatsapp and send neha a message hi`,
`send neha a message from airtel hi`, `neha ko hi message karo`, `rahul ko sms karo ki main aa raha hun`.
WhatsApp opens the chat with the text typed (user presses Send). **Auto-send** (user's choice,
no confirmation card): an Accessibility service (`java/org/pa/assistant/AutoSendService.java`,
only WhatsApp packages) presses Send itself, but only within 20 s after the app opened that chat
and only if WhatsApp's text box holds exactly the requested message; then it returns to the app,
which reports "sent" or "not sent". The user switches it on in Settings > Accessibility (sideloaded
apps may first need "Allow restricted settings"). Risk told to the user: WhatsApp's terms forbid
automation; an account warning/ban is possible. Verified once by the user ("WhatsApp message sent to
<contact>"). On Android 13+ a sideloaded app's accessibility switch is a "restricted setting": after
updates it was found switched off. Fix: Settings > Apps > Local Assistant > 3 dots > "Allow
restricted settings" (on the test phone done with `appops set ... ACCESS_RESTRICTED_SETTINGS allow`);
after that it stayed on across an update. The app also remembers that auto-send was on and, if it
finds it off on start, says so and shows a "Turn on auto-send" button. SMS goes from the chosen SIM after
the approval card (an SMS cannot be taken back). No channel given -> the app asks SMS or WhatsApp.
Unit-tested; on the phone the SMS permission prompt appeared, nothing was sent during testing.
Daily messages: `har subah 8 baje mummy ko good morning message karo`, `every night at 10 send
"good night" to papa on whatsapp`, `roz shaam 6 baje papa ko sms karo ki main nikal gaya`.
Approved once on the proposal card, then the phone's alarm (exact, `setExactAndAllowWhileIdle`)
runs it every day even when the app is closed: **SMS** is sent automatically (SEND_SMS);
**WhatsApp** shows a notification, tap opens the chat with the text typed and the user presses
Send (WhatsApp lets no app send by itself; screen-automation tricks were rejected: against
WhatsApp's terms). Java side: `java/org/pa/assistant/` (receiver, boot receiver), added to the
manifest by `p4a_hook.py`. Each schedule is stored encrypted with its own Android Keystore key so
it survives reboots; the alarm only carries an id. Lock screen shows a neutral notification.
List/delete under **Tasks**. Only "every day" for now (weekdays are refused, not guessed).
Phones that freeze background apps (vivo) need "allow background": asked after approval.
Open apps: lists apps with a launcher icon (manifest `<queries>` for MAIN/LAUNCHER, no
QUERY_ALL_PACKAGES) and starts one. Match order: exact name -> starts with -> contains -> close
spelling ("watsapp"), plus short names (insta, yt, fb). One match opens directly (no approval:
read-only and reversible); several show a list. The audit log never stores the app name.
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

## Look: Lazey UI (from the team's `gui-themes-layout` branch)
The UI in `pa_ui/` (themes, header with wave logo and tagline, greeting orb, chat bubbles, rounded
typing bar with `+` quick prompts / mic / send, slide-out menu, Theme screen with 8 themes,
Calendar month view, quick prompts you can add/delete, Poppins/Inter fonts and Material Icons
Round) was written on that branch on top of v0.3 and integrated by hand into `main.py`, keeping
every feature added on main after v0.3. Integration choices:
- **Package id unchanged** (`org.pa.localassistant`); only the visible name is "Lazey". The branch had
  renamed the package to `org.pa.lazey`, which would install a second, empty app without the
  encrypted data, permissions, battery exemption and auto-send switch.
- Menu: Theme, Calendar, **Tasks** (added: to-dos & reminders with Done/Del, routines with Run/Del and
  their times, daily messages, "allow background" button), Preferences (plus "Clear chat history"),
  Voice (the branch's simpler screen plus "Offline only / Allow online" and the offline speech pack
  status/download, needed for the no-internet requirement).
- Chat history is shown as bubbles; auto-send setup, battery-exemption prompts, timed-routine taps
  and the exact permission messages work as before.
- Verified on the phone: new look, menu with Tasks, Tasks and Voice screens, a command and its reply
  as bubbles, earlier chat restored.

## Run tests (Windows / any OS)
    pip install cryptography pycryptodome
    python -m unittest discover -s tests

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
- `har subah 8 baje mummy ko good morning message karo` / `roz raat 10 baje rahul ko 'good night' sms bhejo`
- `open whatsapp` / `whatsapp kholo` / `youtube open karo` / `insta chalao` / `launch play store`
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
