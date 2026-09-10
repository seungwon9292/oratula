"""Settings and message policy, independent of Discord/network/model downloads."""
from dataclasses import dataclass
import re
import sqlite3

SUPERTONIC_VOICES = tuple(f"{prefix}{i}" for prefix in ("F", "M") for i in range(1, 6))
MODEL_VOICES = {
    "supertonic-3": SUPERTONIC_VOICES,
    "supertonic-2": SUPERTONIC_VOICES,
    "melotts-kr": ("KR",),
    "mms-tts-kor": ("MMS",),
    "qwen3-tts-0.6b": (
        "Sohee", "Vivian", "Serena", "Uncle_Fu", "Dylan",
        "Eric", "Ryan", "Aiden", "Ono_Anna",
    ),
}
MODELS = tuple(MODEL_VOICES)
VOICES = tuple(dict.fromkeys(voice for voices in MODEL_VOICES.values() for voice in voices))


@dataclass(frozen=True)
class Preference:
    model: str = "supertonic-3"
    voice: str = "F1"
    speed: float = 1.05
    enabled: bool = True


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS preferences
            (user_id INTEGER PRIMARY KEY, model TEXT NOT NULL, voice TEXT NOT NULL,
             speed REAL NOT NULL, enabled INTEGER NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS guild_targets
            (guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL)""")

    def get(self, user_id):
        row = self.db.execute(
            "SELECT model, voice, speed, enabled FROM preferences WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return Preference(row[0], row[1], row[2], bool(row[3])) if row else Preference()

    def put(self, user_id, preference):
        p = preference
        if (p.model not in MODELS or p.voice not in MODEL_VOICES[p.model]
                or not 0.7 <= p.speed <= 2.0):
            raise ValueError("Invalid TTS preference")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO preferences VALUES (?, ?, ?, ?, ?)",
                            (user_id, p.model, p.voice, p.speed, int(p.enabled)))

    def set_target(self, guild_id, channel_id):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO guild_targets VALUES (?, ?)",
                            (guild_id, channel_id))

    def get_target(self, guild_id):
        row = self.db.execute("SELECT channel_id FROM guild_targets WHERE guild_id=?",
                              (guild_id,)).fetchone()
        return int(row[0]) if row else None

    def clear_target(self, guild_id):
        with self.db:
            self.db.execute("DELETE FROM guild_targets WHERE guild_id=?", (guild_id,))

    def close(self):
        self.db.close()


def eligible(*, message_guild, session_guild, author_is_bot, author_voice, target_voice):
    return (message_guild is not None and message_guild == session_guild
            and not author_is_bot and author_voice == target_voice)


def clean_text(text, limit=300):
    text = re.sub(r"```.*?```", " 코드 생략 ", text, flags=re.S)
    text = re.sub(r"\|\|.*?\|\|", " 스포일러 생략 ", text, flags=re.S)
    text = re.sub(r"https?://\S+", " 링크 ", text)
    text = re.sub(r"<a?:([A-Za-z0-9_]+):\d+>", r" \1 ", text)
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
