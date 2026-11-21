# Feasibility assessment (Stage 1)

Status labels: **VERIFIED** = run/tested here, **UNVERIFIED** = written but not run on a device or built into an APK, **NOT DONE** = not implemented.

## Provisional target (phone details unknown)
Android 10+ (API 29+), arm64, 4 GB RAM, build on WSL2 Ubuntu. Everything hardware-sensitive is config in `pa/config.py`.

## Stack
| Layer | Choice | Status |
|---|---|---|
| Core logic | Pure Python 3 (stdlib + `cryptography`) | VERIFIED on PC (unit tests) |
| UI | Kivy, one screen | NOT DONE (Stage 2) |
| Packaging | python-for-android v2026.05.09 via Buildozer (Python 3.14.2, Kivy 2.3.1, pycryptodome) | VERIFIED: arm64 and x86_64 APKs build in WSL2 |
| Understanding | `ConstrainedParser`, a rule-based Hinglish/English parser. **Not an LLM.** | VERIFIED |
| LLM backend | Interface exists (`InferenceBackend`). No model bundled. | NOT DONE |
| Vector memory | Hashed word + char-trigram vectors (256-d), cosine search over SQLite rows. **Lexical, not neural embeddings**: it matches shared words/spellings, not meaning. | VERIFIED on PC |
| Storage | SQLite, field-level AES-256-GCM | VERIFIED on PC |
| Key management | Android Keystore wraps a random data key (pyjnius) | VERIFIED on Android 11 x86_64 emulator (create + reuse after restart) |
| Calendar | Opens system calendar insert screen (user taps Save). Reading availability needs READ_CALENDAR. | Emulator: insert screen launches once; form needs a Google account so not inspected |
| Real arm64 phone | Same code, arm64 build | VERIFIED on vivo/iQOO, Android 16 (API 36), arm64, ~6 GB RAM: all 7 acceptance steps pass |

## Native Android needs
- Everything that touches Android goes through pyjnius (Keystore, CalendarContract, Intents, permission prompts). No custom Java is written; if a pyjnius call proves unworkable on a device, that piece needs a small Java class.
- A real on-device LLM needs a native inference library (e.g. llama.cpp built for arm64). I know of no verified python-for-android recipe for it, so I do not claim one. It is the largest open risk. Until measured on a device, the app uses the constrained parser and says so in the UI.

## Packaging risks
1. `cryptography` on python-for-android: a recipe exists but recent versions need a Rust toolchain; may fail to build. Fallback: switch to `pycryptodome` (also has a recipe), same AES-GCM interface in `pa/crypto.py`.
2. Host Python in Ubuntu 26.04 is 3.14; python-for-android may not support it. Fallback: install an older Python via `uv`/`pyenv` for the build.
3. Kivy + SDL2 compile takes 20-40 min the first time.
4. No APK size, RAM or latency numbers are claimed; none were measured.

## Model provisioning (install time vs runtime)
Models are never downloaded at runtime. When an LLM backend is added, the model file is copied onto the phone once at install time (adb push or bundled), and the app only checks that the file exists and loads it. Missing/corrupt file: clear error plus fallback to the constrained parser, labelled as such. No remote API is ever called.

## Encryption facts
- Encrypted: note text, preference text, task details, embeddings (all AES-256-GCM, AAD binds each blob to its row).
- Plaintext: row ids, record kind, timestamps, the audit log (contains only action id, type, states, short status code; no message, contact or note content).
- Key: random 32-byte data key, wrapped by an Android Keystore AES key that never leaves secure hardware/TEE where available. Wrapped key stored in app-private storage.
- No plaintext fallback: if no key provider is available the app refuses to open the database. A dev-only file key exists but requires `PA_ALLOW_INSECURE_DEV_KEY=1` and is not for real data.
- Retrieval decrypts rows in memory to score them (fine at prototype scale). Decrypted text exists in RAM while in use. SQLite journal/temp files may contain only ciphertext fields.
