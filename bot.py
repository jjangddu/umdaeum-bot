import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils.database import init_db

# 로그 설정 - stdout으로 즉시 출력
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("umdaeum")

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)

COGS = [
    "cogs.register",
    "cogs.custom_game",
    "cogs.record",
]


@bot.event
async def on_ready():
    await init_db()

    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"Cog 로드 완료: {cog}")
        except Exception as e:
            logger.error(f"Cog 로드 실패: {cog} - {e}")

    synced = await bot.tree.sync()
    logger.info(f"{bot.user} 로그인 완료!")
    logger.info(f"{len(synced)}개 슬래시 커맨드 동기화 완료")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    logger.error(f"명령어 에러: {error}", exc_info=True)
    if interaction.response.is_done():
        await interaction.followup.send(f"❌ 오류가 발생했습니다: {error}", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ 오류가 발생했습니다: {error}", ephemeral=True)


async def main():
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
