import os, json, logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# -------------------- 기본 설정 --------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "")
DEFAULT_VERIFIED_ROLE_NAME = os.getenv("VERIFIED_ROLE_NAME", "Verified")
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

config = load_config()

intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # Developer Portal > Privileged Intents 에서 Server Members ON
bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------- 유틸 --------------------
def get_guild_cfg(guild_id: int) -> dict:
    if str(guild_id) not in config:
        config[str(guild_id)] = {}
    return config[str(guild_id)]

def get_verified_role(guild: discord.Guild, name_hint: Optional[str] = None) -> Optional[discord.Role]:
    gcfg = get_guild_cfg(guild.id)
    role_id = gcfg.get("verified_role_id")
    role = guild.get_role(role_id) if role_id else None
    if role is None:
        # 이름으로 재탐색
        target_name = name_hint or gcfg.get("verified_role_name") or DEFAULT_VERIFIED_ROLE_NAME
        role = discord.utils.get(guild.roles, name=target_name)
    return role

def get_verify_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    gcfg = get_guild_cfg(guild.id)
    ch_id = gcfg.get("verify_channel_id")
    return guild.get_channel(ch_id) if ch_id else None

def account_old_enough(user: discord.abc.User, min_days: int) -> bool:
    if min_days <= 0:
        return True
    created = user.created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created) >= timedelta(days=min_days)

# -------------------- 인증 버튼 --------------------
WELCOME_TEXT = (
    "🐉 **Dragon’s Den**에 오신 걸 환영합니다!\n"
    "아래 버튼을 눌러 **인증**을 완료하면 모든 채널을 이용할 수 있어요. ✅"
)

SUCCESS_REPLY = "인증 완료! 이제 자유롭게 이용하세요 🎉"
FAIL_NO_ROLE = "인증 역할을 찾지 못했어요. 운영진에게 문의해주세요."
FAIL_PERM = "권한이 부족해 역할을 부여할 수 없어요. (봇 역할 순서/권한 확인)"
FAIL_AGE = "죄송해요. 계정 생성 후 **{days}일**이 지나야 인증할 수 있어요."

class VerifyView(discord.ui.View):
    def __init__(self, min_account_age_days: int):
        super().__init__(timeout=None)
        self.min_days = min_account_age_days

    @discord.ui.button(label="✅ 인증하기", style=discord.ButtonStyle.success, custom_id="dragonsden_verify")
    async def verify(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("서버에서만 사용할 수 있어요.", ephemeral=True)

        guild = interaction.guild
        member: discord.Member = interaction.user
        gcfg = get_guild_cfg(guild.id)
        min_days = int(gcfg.get("min_account_age_days", self.min_days))

        if not account_old_enough(member, min_days):
            return await interaction.response.send_message(FAIL_AGE.format(days=min_days), ephemeral=True)

        role = get_verified_role(guild)
        if role is None:
            return await interaction.response.send_message(FAIL_NO_ROLE, ephemeral=True)

        try:
            if role in member.roles:
                return await interaction.response.send_message("이미 인증되어 있어요!", ephemeral=True)
            await member.add_roles(role, reason="Button verify")
            await interaction.response.send_message(SUCCESS_REPLY, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(FAIL_PERM, ephemeral=True)
        except Exception as e:
            logging.exception("verify error: %s", e)
            await interaction.response.send_message("인증 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.", ephemeral=True)

# -------------------- 이벤트 --------------------
@bot.event
async def on_ready():
    logging.info(f"로그인: {bot.user} ({bot.user.id})")
    # 글로벌 동기화
    try:
        await bot.tree.sync()
        logging.info("슬래시 커맨드 동기화
