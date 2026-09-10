# Oratula (Faster Qwen edition)

This edition preserves all original Discord commands, voices, preferences, and
Supertonic/MMS engines. MeloTTS has been removed. `qwen3-tts-0.6b` uses FasterQwen3TTS with
CUDA graphs and SDPA. FlashAttention compilation is not required. Qwen requires
an NVIDIA CUDA GPU; the CPU models remain available without one.

FasterQwen is pinned to revision `a70afc0f81f7f5f8801c3227968f1102f43f211c`
(0.3.2) for compatibility with the existing Transformers 4 dependencies.
The WSL virtual environment is `~/.local/share/oratula-qwen/venv`.
Run `bash setup.sh` in WSL, then `./start.ps1` from Windows or `bash start.sh`
from WSL. Use only one bot instance per Discord token.

The first Qwen request captures CUDA graphs and takes longer. Audio still plays
after the full clip is generated; Discord streaming is not implemented here.
The bot warms the 1.7B Qwen model in the background at startup, so wait for its
`[예열 완료]` log before judging the first Discord request.

`qwen3-tts-1.7b` uses FasterQwen + Triton on WSL/Linux (BF16, SDPA,
layers 0–23 patched before graph capture; no KV quantization).
Select `/oratula-voice model:qwen3-tts-1.7b voice:Sohee speed:1.0`.
Set `QWEN_TRITON=0` in `.env` and restart to use plain FasterQwen for 1.7B.
Native Windows uses plain FasterQwen. The 0.6B option remains unchanged.
Both Qwen sizes need CUDA. Changing size loads another model into GPU memory;
restart the bot to release models loaded earlier if VRAM is tight.

Use the WSL venv Python to run `benchmark_qwen.py --model qwen3-tts-1.7b
--backend hybrid --runs 5` (on one line). Compare with `--backend faster`.
Reports and WAVs are written to `data/`; loading is excluded from warm averages.
The report separates token generation and waveform decoding using synchronized
wall-clock measurements. Benchmark one process at a time with other GPU work idle.

A local Korean TTS bot for Discord. Reads server messages from users in the designated voice channel, with individual voice settings.

## Setup and run

Install Python 3.12 and Git. Linux also requires `python3.12-venv`. Qwen requires an NVIDIA CUDA GPU.

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Linux:

```bash
bash setup.sh
bash start.sh
```

For Windows with an NVIDIA GPU, WSL2 is recommended for Qwen. Install and prepare the Ubuntu distribution first, then run `bash setup.sh` inside WSL. After that, launching `start.ps1` from Windows forwards execution to WSL automatically; use `start.ps1 -Windows` only to run the native Windows environment.

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
| `mms-tts-kor` | MMS |
| `qwen3-tts-0.6b` | Sohee, Vivian, Serena, Uncle_Fu, Dylan, Eric, Ryan, Aiden, Ono_Anna |
| `qwen3-tts-1.7b` | Same voices; FasterQwen + Triton on WSL/Linux |

Default: Supertonic 3 / F1 / 1.0×. Speed range: 0.7–2.0×. Qwen speaks Korean with every voice; Sohee is its native Korean speaker. Qwen loads on first use and adjusts speed after synthesis. Playback starts after the whole clip is generated.

Optional `.env` settings: `DISCORD_GUILD_ID`, `BOT_OWNER_IDS` (comma-separated IDs), and `FFMPEG_PATH`. Settings are stored in `data/settings.sqlite3`; model downloads are cached under `data/`.

## Behavior

- Reads accessible text channels, voice-channel chat, and threads. Excludes DMs, bots, edits, and attachments.
- Preserves accepted message order within each server. Slow models delay later messages in that server.
- CPU and GPU models use separate workers; different servers can use them concurrently.
- Limits: 300 characters, 60 seconds of playback, 30 queued messages per server, and one accepted message per user per second.
- Messages older than two minutes are discarded. Inference exceeding two minutes or a crashed worker triggers replacement for subsequent requests.
- Leaves empty channels within about 10 seconds, or after 30 minutes without an eligible message.
- Remove View Channel permission from channels that must not be read. Run one bot instance per working directory.

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

Use `prepare.py --models mms-tts-kor qwen3-tts-0.6b` to check selected models. For failures, check `/oratula-status`, bot logs, permissions, and channel membership.

## Licenses

Model and dependency licenses apply separately: [Supertonic](https://github.com/supertone-inc/supertonic-py), [Supertonic 3](https://huggingface.co/Supertone/supertonic-3), [Supertonic 2](https://huggingface.co/Supertone/supertonic-2), [MMS Korean](https://huggingface.co/facebook/mms-tts-kor), [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), and [FasterQwen3TTS](https://github.com/andimarafioti/faster-qwen3-tts). MMS weights use CC-BY-NC 4.0.
