from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import io
import logging
import os
from pathlib import Path
import time

import discord
from discord import app_commands
from dotenv import load_dotenv
import imageio_ffmpeg

from core import MODEL_VOICES, MODELS, Preference, Store, eligible, clean_text
from engine import Engine, DATA

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("tts_bot")
IDLE_TIMEOUT_SECONDS = 30 * 60
IDLE_CHECK_INTERVAL_SECONDS = 10
LOG_DIVIDER = "=" * 64


def configure_logging():
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    logging.getLogger("discord.player").setLevel(logging.WARNING)


def log_block(title, *lines):
    content = "\n".join((title, *lines))
    log.info("\n%s\n%s\n%s\n", LOG_DIVIDER, content, LOG_DIVIDER)


class VoiceChannelReference(app_commands.Transformer):
    """Keep the raw interaction channel so uncached channels can be fetched by ID."""

    @property
    def type(self):
        return discord.AppCommandOptionType.channel

    @property
    def channel_types(self):
        return [discord.ChannelType.voice]

    async def transform(self, interaction, value):
        return value


@dataclass
class Utterance:
    user_id: int
    text: str
    created: float = field(default_factory=time.monotonic)


@dataclass
class Session:
    guild: discord.Guild
    channel_id: int
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=30))
    generation: int = 0
    task: asyncio.Task | None = None
    idle_task: asyncio.Task | None = None
    last_message: dict = field(default_factory=dict)
    last_error: str | None = None
    last_activity: float = field(default_factory=time.monotonic)

    def clear(self):
        self.generation += 1
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()


class TTSBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        DATA.mkdir(parents=True, exist_ok=True)
        self.tree = app_commands.CommandTree(self)
        self.store = Store(DATA / "settings.sqlite3")
        self.engine = Engine()
        self.sessions: dict[int, Session] = {}
        self.controls: dict[int, asyncio.Lock] = {}
        self.synced_guilds: set[int] = set()
        self.warmup_task: asyncio.Task | None = None
        self.owners = {int(v.strip()) for v in os.getenv("BOT_OWNER_IDS", "").split(",") if v.strip()}
        self.ffmpeg = os.getenv("FFMPEG_PATH") or imageio_ffmpeg.get_ffmpeg_exe()

    async def setup_hook(self):
        # Keep command definitions locally, but remove global registrations so
        # Discord shows only one guild-scoped copy per server.
        commands = self.tree.get_commands()
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        for command in commands:
            self.tree.add_command(command)
        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            commands = await self.tree.sync(guild=guild)
            self.synced_guilds.add(guild.id)
            log.info("Synced %s commands to configured guild %s", len(commands), guild.id)

    async def on_ready(self):
        guild_lines = tuple(f"  - {guild.name} ({guild.id})" for guild in self.guilds)
        log_block(
            "Oratula 온라인",
            f"봇 계정: {self.user} ({self.user.id})",
            f"연결된 서버: {len(self.guilds)}개",
            *(guild_lines or ("  - 없음",)),
        )
        if self.warmup_task is None:
            self.warmup_task = asyncio.create_task(self.warmup_models())
        for guild in self.guilds:
            await self.sync_guild_commands(guild)

    async def warmup_models(self):
        preferences = (
            Preference(model="qwen3-tts-1.7b", voice="Sohee", speed=1.0),
            Preference(model="supertonic-3", voice="F1", speed=1.0),
            Preference(model="supertonic-2", voice="F1", speed=1.0),
            Preference(model="melotts-kr", voice="KR", speed=1.0),
            Preference(model="mms-tts-kor", voice="MMS", speed=1.0),
        )
        log_block("TTS 모델 예열 시작", "모델을 차례로 메모리에 불러옵니다.")
        for preference in preferences:
            try:
                await self.engine.synthesize("준비", preference)
                log.info("[예열 완료] %s", preference.model)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning("TTS warm-up failed for %s: %s",
                            preference.model, type(error).__name__)
        log_block("TTS 모델 예열 종료", "Oratula를 사용할 준비가 됐습니다.")

    async def on_guild_join(self, guild):
        log.info("Joined guild: %s (%s)", guild.name, guild.id)
        await self.sync_guild_commands(guild)

    async def sync_guild_commands(self, guild):
        if guild.id in self.synced_guilds:
            return
        try:
            self.tree.copy_global_to(guild=guild)
            commands = await self.tree.sync(guild=guild)
            self.synced_guilds.add(guild.id)
            log.info("Synced %s commands to guild %s", len(commands), guild.id)
        except Exception as error:
            log.warning("Command sync failed for guild %s: %s", guild.id, type(error).__name__)

    async def ensure_session(self, guild, channel):
        async with self.controls.setdefault(guild.id, asyncio.Lock()):
            if self.store.get_target(guild.id) != channel.id:
                return None
            existing = self.sessions.get(guild.id)
            voice = guild.voice_client
            if existing and voice and voice.is_connected() and voice.channel.id == channel.id:
                return existing
            if existing or voice:
                await self.stop_session(guild)
            try:
                await channel.connect(timeout=30, self_deaf=True)
            except Exception:
                if guild.voice_client:
                    await guild.voice_client.disconnect(force=True)
                raise
            session = Session(guild, channel.id)
            self.sessions[guild.id] = session
            session.task = asyncio.create_task(self.worker(session))
            session.idle_task = asyncio.create_task(self.idle_monitor(session))
            return session

    def control_allowed(self, interaction):
        return interaction.user.id in self.owners or interaction.permissions.manage_guild

    async def stop_session(self, guild, *, forget=False):
        session = self.sessions.pop(guild.id, None)
        if session:
            session.clear()
        if forget:
            self.store.clear_target(guild.id)
        voice = guild.voice_client
        if voice:
            voice.stop()
        if session and session.task:
            session.task.cancel()
            await asyncio.gather(session.task, return_exceptions=True)
        if session and session.idle_task and session.idle_task is not asyncio.current_task():
            session.idle_task.cancel()
            await asyncio.gather(session.idle_task, return_exceptions=True)
        if voice:
            await voice.disconnect(force=True)

    async def idle_monitor(self, session):
        while self.sessions.get(session.guild.id) is session:
            await asyncio.sleep(IDLE_CHECK_INTERVAL_SECONDS)
            if self.sessions.get(session.guild.id) is not session:
                return
            voice = session.guild.voice_client
            if voice is None or not voice.is_connected():
                return
            channel = voice.channel
            humans = [member for member in getattr(channel, "members", []) if not member.bot]
            if not humans:
                log.info("Leaving empty voice channel in guild %s", session.guild.id)
                await self.stop_session(session.guild)
                return
            if time.monotonic() - session.last_activity >= IDLE_TIMEOUT_SECONDS:
                log.info("Leaving idle voice channel in guild %s", session.guild.id)
                await self.stop_session(session.guild)
                return

    def still_present(self, session, user_id):
        voice = session.guild.voice_client
        member = session.guild.get_member(user_id)
        return (self.sessions.get(session.guild.id) is session
                and voice is not None and voice.is_connected()
                and voice.channel.id == session.channel_id
                and member is not None and member.voice is not None
                and member.voice.channel is not None
                and member.voice.channel.id == session.channel_id
                and self.store.get(user_id).enabled)

    async def worker(self, session):
        while True:
            item = await session.queue.get()
            generation = session.generation
            try:
                if time.monotonic() - item.created > 120 or not self.still_present(session, item.user_id):
                    continue
                data = await self.engine.synthesize(item.text, self.store.get(item.user_id))
                if (generation != session.generation or not self.still_present(session, item.user_id)
                        or time.monotonic() - item.created > 120):
                    continue
                source = discord.FFmpegOpusAudio(
                    io.BytesIO(data),
                    pipe=True,
                    executable=self.ffmpeg,
                    options="-vn -t 60 -loglevel error",
                )
                try:
                    done = asyncio.get_running_loop().create_future()
                    loop = asyncio.get_running_loop()

                    def finish(error, done=done):
                        if not done.done():
                            if error:
                                done.set_exception(error)
                            else:
                                done.set_result(None)

                    def after(error, finish=finish):
                        loop.call_soon_threadsafe(finish, error)

                    voice = session.guild.voice_client
                    voice.play(source, after=after)
                    await asyncio.wait_for(done, timeout=75)
                finally:
                    voice = session.guild.voice_client
                    if voice:
                        voice.stop()
                    source.cleanup()
                session.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Avoid persisting message text or model exception payloads.
                session.last_error = type(error).__name__
                log.warning("Synthesis/playback failed in guild %s: %s", session.guild.id, session.last_error)
            finally:
                session.queue.task_done()

    async def on_message(self, message):
        if message.guild is None:
            return
        session = self.sessions.get(message.guild.id)
        voice = message.guild.voice_client
        if (session is not None and (voice is None or not voice.is_connected()
                or voice.channel.id != session.channel_id)):
            session = None
        if session is None and not message.author.bot:
            target_id = self.store.get_target(message.guild.id)
            state = getattr(message.author, "voice", None)
            if target_id and state and state.channel and state.channel.id == target_id:
                channel = message.guild.get_channel(target_id)
                if isinstance(channel, discord.VoiceChannel):
                    try:
                        session = await self.ensure_session(message.guild, channel)
                    except Exception as error:
                        log.warning("Automatic voice join failed in guild %s: %s",
                                    message.guild.id, type(error).__name__)
                        return
        if not session:
            return
        state = getattr(message.author, "voice", None)
        author_voice = state.channel.id if state and state.channel else None
        if not eligible(message_guild=message.guild.id, session_guild=session.guild.id,
                        author_is_bot=message.author.bot, author_voice=author_voice,
                        target_voice=session.channel_id):
            return
        if not self.still_present(session, message.author.id):
            return
        text = clean_text(message.clean_content)
        if not text:
            return
        session.last_activity = time.monotonic()
        if not self.store.get(message.author.id).enabled:
            return
        now = time.monotonic()
        if now - session.last_message.get(message.author.id, 0) < 1:
            return
        if session.queue.full():
            return
        session.last_message[message.author.id] = now
        session.queue.put_nowait(Utterance(message.author.id, text))

    async def on_voice_state_update(self, member, before, after):
        session = self.sessions.get(member.guild.id)
        if not session:
            return
        if member.id == self.user.id:
            if after.channel is None or after.channel.id != session.channel_id:
                session.clear()
                session.last_error = "봇 연결이 변경되었습니다. /oratula-start로 다시 지정하세요."
        elif after.channel is None or after.channel.id != session.channel_id:
            session.last_message.pop(member.id, None)

    async def close(self):
        if self.warmup_task:
            self.warmup_task.cancel()
            await asyncio.gather(self.warmup_task, return_exceptions=True)
        for session in list(self.sessions.values()):
            try:
                await self.stop_session(session.guild)
            except Exception as error:
                log.warning("Voice cleanup failed: %s", type(error).__name__)
        try:
            await super().close()
        finally:
            self.engine.close()
            self.store.close()


def register_commands(bot):
    async def voice_autocomplete(interaction: discord.Interaction, current: str):
        selected_model = getattr(interaction.namespace, "model", None)
        if selected_model is None:
            selected_model = bot.store.get(interaction.user.id).model
        available = MODEL_VOICES.get(selected_model, ())
        query = current.casefold()
        return [
            app_commands.Choice(name=voice, value=voice)
            for voice in available
            if query in voice.casefold()
        ]

    @bot.tree.command(name="oratula-start", description="음성방을 지정하고 참가자의 모든 서버 채팅을 읽습니다")
    @app_commands.guild_only()
    @app_commands.describe(channel="봇이 참가할 일반 음성 채널 (스테이지 채널 제외)")
    async def start(
        interaction: discord.Interaction,
        channel: app_commands.Transform[app_commands.AppCommandChannel, VoiceChannelReference],
    ):
        if not bot.control_allowed(interaction):
            await interaction.response.send_message("서버 관리 권한 또는 BOT_OWNER_IDS 등록이 필요합니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if channel.type is not discord.ChannelType.voice:
            await interaction.followup.send("스테이지·텍스트 채널이 아닌 일반 음성 채널을 선택해 주세요.",
                                            ephemeral=True)
            return
        resolved_channel = interaction.guild.get_channel(channel.id)
        if resolved_channel is None:
            try:
                resolved_channel = await interaction.guild.fetch_channel(channel.id)
            except (discord.Forbidden, discord.NotFound):
                await interaction.followup.send(
                    "해당 음성 채널을 봇이 볼 수 없습니다. 채널 권한에서 Oratula에 채널 보기·연결·말하기를 허용해 주세요.",
                    ephemeral=True)
                return
        if not isinstance(resolved_channel, discord.VoiceChannel):
            await interaction.followup.send("일반 음성 채널을 선택해 주세요.", ephemeral=True)
            return
        channel = resolved_channel
        permissions = channel.permissions_for(interaction.guild.me)
        if not (permissions.view_channel and permissions.connect and permissions.speak):
            await interaction.followup.send("해당 음성방에서 봇에 채널 보기·연결·말하기 권한을 주세요.", ephemeral=True)
            return
        async with bot.controls.setdefault(interaction.guild_id, asyncio.Lock()):
            bot.store.set_target(interaction.guild_id, channel.id)
            await bot.stop_session(interaction.guild)
        await interaction.followup.send(
            f"✅ **Oratula 음성방을 저장했습니다.**\n\n"
            f"🔊 **저장된 음성방:** {channel.mention}\n"
            "💬 **읽는 범위:** 이 음성방 참가자가 같은 서버의 봇 접근 가능 채널에 작성한 메시지\n"
            "👤 **대상:** 현재 지정한 음성방에 들어와 있는 사용자\n\n"
            "▶️ **자동 입장:** 이 음성방 참가자가 채팅을 쓸 때 들어와 읽기 시작합니다.\n"
            "⏱️ **자동 퇴장:** 사람이 없으면 최대 10초 안에, 30분 동안 채팅이 없으면 자동으로 나갑니다.\n\n"
            "개인 설정은 아래 명령어를 사용하세요.\n"
            "• `/oratula-voice` — TTS 모델·목소리·속도 선택\n"
            "• `/oratula-toggle enabled:False` — 내 메시지 낭독 끄기\n"
            "• `/oratula-toggle enabled:True` — 내 메시지 낭독 켜기\n"
            "• `/oratula-clear` — 현재 재생과 대기열 취소\n"
            "• `/oratula-status` — 연결 상태와 대기열 확인\n\n"
            "🎭 **Qwen 1.7B 감정 표현:** `[기쁘게] 오늘 정말 좋아!`처럼 메시지 맨 앞에 지시를 적으세요.\n"
            "대괄호 안은 음성으로 읽지 않고 Qwen의 감정·말투 지시로 사용합니다.\n\n"
            "메시지가 읽히지 않으면 본인이 이 음성방에 참가해 있는지 확인하세요.",
            ephemeral=True)

    @bot.tree.command(name="oratula-stop", description="낭독을 중지하고 음성방을 나갑니다")
    @app_commands.guild_only()
    async def stop(interaction: discord.Interaction):
        if not bot.control_allowed(interaction):
            await interaction.response.send_message("서버 관리 권한 또는 BOT_OWNER_IDS 등록이 필요합니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with bot.controls.setdefault(interaction.guild_id, asyncio.Lock()):
            await bot.stop_session(interaction.guild, forget=True)
        await interaction.followup.send("낭독을 중지했습니다.", ephemeral=True)

    @bot.tree.command(name="oratula-voice", description="내 TTS 모델·목소리·속도를 선택하고 저장합니다")
    @app_commands.guild_only()
    @app_commands.describe(model="먼저 TTS 모델을 선택하세요",
                           voice="선택한 모델에서 사용할 수 있는 목소리",
                           speed="낭독 속도 (0.7~2.0)")
    @app_commands.choices(model=[app_commands.Choice(name=m, value=m) for m in MODELS])
    @app_commands.autocomplete(voice=voice_autocomplete)
    async def settings(interaction: discord.Interaction, model: str | None = None,
                       voice: str | None = None, speed: app_commands.Range[float, 0.7, 2.0] | None = None):
        await interaction.response.defer(ephemeral=True)
        current = bot.store.get(interaction.user.id)
        chosen_model = model or current.model
        chosen_voice = voice or current.voice
        available_voices = MODEL_VOICES[chosen_model]
        if chosen_voice not in available_voices:
            chosen_voice = available_voices[0]
        updated = replace(current, model=chosen_model, voice=chosen_voice,
                          speed=speed if speed is not None else current.speed)
        bot.store.put(interaction.user.id, updated)
        await interaction.followup.send(
            f"내 설정: {updated.model} / {updated.voice} / {updated.speed:.2f}배속 / "
            f"낭독 {'켜짐' if updated.enabled else '꺼짐'}", ephemeral=True)

    @bot.tree.command(name="oratula-toggle", description="내 채팅 낭독을 켜거나 끕니다")
    @app_commands.guild_only()
    async def toggle(interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        bot.store.put(interaction.user.id, replace(bot.store.get(interaction.user.id), enabled=enabled))
        await interaction.followup.send(f"내 채팅 낭독을 {'켰습니다' if enabled else '껐습니다'}.", ephemeral=True)

    @bot.tree.command(name="oratula-clear", description="현재 낭독과 대기 중인 메시지를 모두 취소합니다")
    @app_commands.guild_only()
    async def clear(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        session = bot.sessions.get(interaction.guild_id)
        state = getattr(interaction.user, "voice", None)
        participant = session and state and state.channel and state.channel.id == session.channel_id
        if not (bot.control_allowed(interaction) or participant):
            await interaction.followup.send("지정 음성방 참가자 또는 관리자만 사용할 수 있습니다.", ephemeral=True)
            return
        if session:
            session.clear()
            if interaction.guild.voice_client:
                interaction.guild.voice_client.stop()
        await interaction.followup.send("현재 낭독과 대기열을 비웠습니다.", ephemeral=True)

    @bot.tree.command(name="oratula-status", description="연결·대기열·최근 오류를 확인합니다")
    @app_commands.guild_only()
    async def status(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        session = bot.sessions.get(interaction.guild_id)
        if not session:
            target_id = bot.store.get_target(interaction.guild_id)
            if target_id:
                text = f"대기 상태입니다. 저장된 방: <#{target_id}> · 참가자가 채팅하면 자동으로 들어갑니다."
            else:
                text = "중지 상태입니다. /oratula-start로 음성방을 지정하세요."
        else:
            vc = interaction.guild.voice_client
            connected = vc is not None and vc.is_connected() and vc.channel.id == session.channel_id
            text = (f"지정 방: <#{session.channel_id}> · 연결: {connected} · 대기: {session.queue.qsize()}개\n"
                    f"최근 오류: {session.last_error or '없음'}")
        await interaction.followup.send(text, ephemeral=True)

    @bot.tree.error
    async def on_error(interaction, error):
        original = getattr(error, "original", error)
        command_name = getattr(getattr(interaction, "command", None), "qualified_name", "unknown")
        age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
        log.warning("Command failed: /%s · %s · %.2fs · acknowledged=%s",
                    command_name, type(original).__name__, age, interaction.response.is_done())
        if isinstance(original, discord.NotFound) or getattr(original, "code", None) in (10062, 40060):
            log.warning("Discord command response expired: /%s", command_name)
            return
        if isinstance(original, app_commands.TransformerError):
            text = "음성 채널을 선택하지 못했습니다. `/oratula-start`에서 일반 음성 채널을 다시 선택해 주세요."
        else:
            text = f"실행 실패 ({type(original).__name__}). 봇 권한·네트워크·설정을 확인하세요."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.NotFound:
            # Discord can expire an interaction while an argument is being transformed.
            log.warning("Could not send command error response: interaction expired")


def main():
    load_dotenv(ROOT / ".env")
    configure_logging()
    log_block("Oratula 시작", "Discord 연결을 준비하고 있습니다.")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit(".env 파일의 DISCORD_TOKEN을 입력하세요. 토큰을 채팅에 보내지 마세요.")
    bot = TTSBot()
    register_commands(bot)
    bot.run(token)


if __name__ == "__main__":
    main()
