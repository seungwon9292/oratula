# Oratula

A local Discord TTS bot that reads messages aloud with individual voice settings.
Supports Supertonic, MeloTTS, MMS, and Qwen3-TTS.

## Setup and run

Install Git and Python 3.12. Linux and WSL can use `uv` to install Python 3.12
when it is not available from the system package manager. Qwen additionally
requires an NVIDIA CUDA GPU.

Windows with WSL2 (recommended for Qwen):

```bash
# Run once inside WSL
bash setup.sh
```

```powershell
# Run from Windows whenever you want to start the bot
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Native Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Windows
```

Linux:

```bash
bash setup.sh
bash start.sh
```

`start.ps1` starts the Ubuntu WSL distribution by default. Pass `-Distro NAME`
if your distribution uses another name.

Between setup and startup, set `DISCORD_TOKEN` in the generated `.env`. Enable **Message Content Intent** in the Discord Developer Portal. Invite the bot with `bot` and `applications.commands` scopes and View Channels, Send Messages, Connect, and Speak permissions.

Setup downloads models and generates sample WAVs in `data/`; initial downloads may take several minutes. Rerun setup after dependency updates. Restart the bot after code changes. Press `Ctrl+C` to stop.

## Commands

| Command | Action |
|---|---|
| `/oratula-start channel:` | Set the voice channel; join when a participant sends a message |
| `/oratula-stop` | Stop playback and forget the channel |
| `/oratula-voice model: voice: speed:` | View or update personal settings |
| `/oratula-toggle enabled:` | Enable or disable personal TTS |
| `/oratula-clear` | Stop playback and discard queued messages |
| `/oratula-status` | Show connection, queue, and latest error |

Start and stop require Manage Server permission or registration in `BOT_OWNER_IDS`.

## Models

| Model option | Voices |
|---|---|
| `supertonic-3` | F1–F5, M1–M5 |
| `supertonic-2` | F1–F5, M1–M5 |
| `melotts-kr` | KR |
| `mms-tts-kor` | MMS |
| `qwen3-tts-1.7b` | Sohee, Vivian, Serena, Uncle_Fu, Dylan, Eric, Ryan, Aiden, Ono_Anna |

Default: Supertonic 3 / F1 / 1.0×. Speed range: 0.7–2.0×. Models are warmed
in the background at startup. Playback begins after each clip is fully generated.

Prefix a message with an instruction to control Qwen's emotion and delivery:
`[happily and excitedly] Something really wonderful happened today!`. The
instruction is not spoken. Other models speak only the text after the tag.

Set `QWEN_TRITON=0` in `.env` to disable the Triton backend on Linux or WSL.
The other models can run on CPU.

Optional `.env` settings: `DISCORD_GUILD_ID`, `BOT_OWNER_IDS` (comma-separated IDs), and `FFMPEG_PATH`. Settings are stored in `data/settings.sqlite3`; model downloads are cached under `data/`.

## Behavior

- Reads accessible text channels, voice-channel chat, and threads. Excludes DMs, bots, edits, and attachments.
- Preserves accepted message order within each server. Slow models delay later messages in that server.
- CPU and GPU models use separate workers; different servers can use them concurrently.
- Limits: 300 characters, 60 seconds of playback, 30 queued messages per server, and one accepted message per user per second.
- Messages older than two minutes are discarded. Inference exceeding two minutes or a crashed worker triggers replacement for subsequent requests.
- Leaves empty channels within about 10 seconds, or after 30 minutes without an eligible message.
- Remove View Channel permission from channels that must not be read. Run only one bot instance per Discord token.

## Tests

Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe prepare.py
```

Linux:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python prepare.py
```

WSL:

```bash
~/.local/share/oratula-qwen/venv/bin/python -m unittest discover -s tests -v
~/.local/share/oratula-qwen/venv/bin/python prepare.py
```

Use `prepare.py --models mms-tts-kor qwen3-tts-1.7b` to check selected models. For failures, check `/oratula-status`, bot logs, permissions, and channel membership.

## Licenses

Oratula's source code is licensed under the [MIT License](LICENSE).

Models and dependencies retain their respective licenses:
[Supertonic](https://github.com/supertone-inc/supertonic-py),
[Supertonic 3](https://huggingface.co/Supertone/supertonic-3),
[Supertonic 2](https://huggingface.co/Supertone/supertonic-2),
[MMS Korean](https://huggingface.co/facebook/mms-tts-kor),
[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), and
[FasterQwen3TTS](https://github.com/andimarafioti/faster-qwen3-tts).
MMS weights use CC-BY-NC 4.0.
