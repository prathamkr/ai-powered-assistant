# Open-source repositories used

Rule for everything below: the app runs **only on the phone, with no internet**. Nothing from these
repositories adds a network call, a cloud model or a download at runtime.

| Repository | Licence | Used? | What for | Where in this project |
|---|---|---|---|---|
| [agents-io/PokeClaw](https://github.com/agents-io/PokeClaw) (commit `936eca3`, 2026-06-02) | Apache-2.0 | **Yes**: code ported + design | Information retrieval, to-dos, workflows, command routing | see below |
| [omnimind-ai/OmniBot](https://github.com/omnimind-ai/OmniBot) (OpenOmniBot) | AGPL-3.0 for non-commercial personal use only; *forbidden for any organisation* without a commercial licence | **No code** | Only the general idea that scheduled tasks, alarms and calendar queries belong in a phone assistant (ideas are not copied code) | — |
| [NimbleEdge/assistant](https://github.com/NimbleEdge/assistant) | Apache-2.0 | **No** | It needs a Llama 3.2 1B model plus its own C++/ONNX runtime; too heavy for this Python APK on a 6 GB phone, and its full app code is still on its roadmap | — |
| [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (via the team's `add-pocketmind-voice` branch) | Apache-2.0 | **No** | Its recogniser model is English-only and adds ~100 MB; the phone's own on-device recogniser is used instead | — |

## PokeClaw: exactly what was taken

PokeClaw is an on-device AI phone agent. Its local mode uses a Gemma 4 model (~2.6 GB download,
8 GB RAM minimum, 2-3 minutes per task on a Pixel 8 Pro). **The model was not used**: it needs the
internet once to download, does not fit the 6 GB target phone, and is too slow. What was used:

| PokeClaw part | What we did with it | Our file | Requirement it serves |
|---|---|---|---|
| `tool/impl/GetDeviceInfoTool.java` (battery, storage, device, screen, network, time) | **Code ported** to Python/pyjnius. Changed: WiFi name and Bluetooth device names left out (they need location / nearby-devices permissions); free RAM and next alarm added; low-battery, hot-battery and full-storage advice added | `pa/adapters/device_info.py`, `Assistant._info` | Information retrieval, decision support |
| `agent/knowledge/KbAddTodoTool.kt` (to-do with optional due date and priority) | **Data shape reused** (text + due date + high/medium/low). Added: time-based one-time reminders that fire even when the app is closed (Android alarm + notification), Hinglish phrasing, "mark done" | `pa/everyday.py: parse_todo`, `Assistant._add_todo/_list_todos/_done_todo`, `java/.../DailyMessages.saveReminder` | Scheduling, workflow management |
| `agent/skill/Skill.kt` + `SkillExecutor.kt` (a skill = named list of steps run deterministically) | **Design reused** for *routines*: a named list of our own commands, saved encrypted, run in order without any model. Changed: steps are plain sentences the user writes; unknown steps are refused when the routine is saved | `pa/everyday.py: parse_routine`, `Assistant._create_routine/_run_routine/_run_steps` | Workflow management |
| `agent/PipelineRouter.kt` (detect "and/then" compound tasks before single-command matching) | **Design reused**: a line with and/then/phir/; is split, but only if every part is a known command; each part then runs in order. PokeClaw sends compound tasks to its LLM; we run them with the rule parser. Added: a second app is not opened while another app (WhatsApp, a call) is in front | `Assistant._compound_parts/_run_steps` | Autonomous execution of everyday tasks |

## Our own additions (not from any repository)

- **Daily plan / decision support** ("aaj ka plan", "what should I do now"): calendar busy times,
  in-app tasks, daily messages, to-dos (overdue first, then priority), next alarm, battery
  advice, and a suggested free 30-minute slot for the most urgent to-do, using the saved
  preference (e.g. "I like working in the evening") and the existing planner.
- **Context**: "usko call karo" / "send her hi" uses the person from the last call or message.
