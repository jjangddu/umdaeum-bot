import discord
from discord import app_commands
from discord.ext import commands

from utils.database import (
    register_user, get_user, set_positions, update_user_stats,
    find_user_by_riot_id, get_effective_elo, set_elo_override,
)
from utils.riot_api import fetch_full_profile, TIER_EMOJI

POSITION_CHOICES = [
    app_commands.Choice(name="탑", value="TOP"),
    app_commands.Choice(name="정글", value="JUNGLE"),
    app_commands.Choice(name="미드", value="MID"),
    app_commands.Choice(name="원딜", value="ADC"),
    app_commands.Choice(name="서포터", value="SUPPORT"),
]


async def _do_register(discord_id: int, riot_name: str, riot_tag: str) -> tuple[discord.Embed | None, str | None]:
    """등록 공통 로직. 성공 시 (embed, None), 실패 시 (None, 에러메시지)"""
    profile = await fetch_full_profile(riot_name, riot_tag)
    if not profile:
        return None, "❌ 소환사를 찾을 수 없습니다. 이름과 태그를 확인해주세요."

    # 중복 등록 방지
    existing = await find_user_by_riot_id(profile["name"], profile["tag"])
    if existing and existing["discord_id"] != discord_id:
        return None, f"❌ **{profile['name']}#{profile['tag']}**는 이미 다른 사용자가 등록한 닉네임입니다."

    await register_user(discord_id, profile["name"], profile["tag"])
    await update_user_stats(
        discord_id,
        profile["tier"],
        profile["rank"],
        profile["wins"],
        profile["losses"],
        profile["level"],
        profile["lp"],
    )

    tier_display = profile["tier"]
    emoji = TIER_EMOJI.get(tier_display, "")
    rank_str = f"{tier_display} {profile['rank']}" if profile["rank"] else tier_display

    embed = discord.Embed(title="✅ 등록 완료!", color=discord.Color.green())
    embed.add_field(name="소환사", value=f"**{profile['name']}#{profile['tag']}**", inline=False)
    embed.add_field(name="티어", value=f"{emoji} {rank_str} ({profile['lp']} LP)", inline=True)
    embed.add_field(name="레벨", value=str(profile["level"]), inline=True)
    embed.add_field(
        name="솔랭 전적",
        value=f"{profile['wins']}승 {profile['losses']}패 "
              f"(승률 {profile['wins'] * 100 // max(profile['wins'] + profile['losses'], 1)}%)",
        inline=False,
    )

    return embed, None


class Register(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── 닉네임 등록 ──

    @app_commands.command(name="등록", description="롤 닉네임을 등록합니다 (예: Hide on bush#KR1)")
    @app_commands.describe(
        riot_name="소환사 이름",
        riot_tag="태그라인 (예: KR1)",
    )
    async def register(self, interaction: discord.Interaction, riot_name: str, riot_tag: str):
        await interaction.response.defer()

        embed, error = await _do_register(interaction.user.id, riot_name, riot_tag)
        if error:
            await interaction.followup.send(error)
        else:
            await interaction.followup.send(embed=embed)

    # ── 관리자 대리 등록 ──

    @app_commands.command(name="대리등록", description="[관리자] 다른 유저의 롤 닉네임을 등록합니다")
    @app_commands.describe(
        member="등록할 디스코드 유저",
        riot_name="소환사 이름",
        riot_tag="태그라인 (예: KR1)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_register(
        self, interaction: discord.Interaction,
        member: discord.Member, riot_name: str, riot_tag: str,
    ):
        await interaction.response.defer()

        embed, error = await _do_register(member.id, riot_name, riot_tag)
        if error:
            await interaction.followup.send(error)
        else:
            embed.title = f"✅ {member.display_name} 등록 완료! (관리자 대리등록)"
            await interaction.followup.send(embed=embed)

    @admin_register.error
    async def admin_register_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ 관리자 권한이 필요합니다.", ephemeral=True)

    # ── 프로필 조회 ──

    @app_commands.command(name="프로필", description="등록된 프로필을 조회합니다")
    @app_commands.describe(member="조회할 사용자 (비워두면 본인)")
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        user = await get_user(target.id)

        if not user:
            await interaction.response.send_message("❌ 등록되지 않은 사용자입니다. `/등록`으로 먼저 등록해주세요.")
            return

        tier = user["tier"] or "UNRANKED"
        rank = user["rank"] or ""
        emoji = TIER_EMOJI.get(tier, "")
        rank_str = f"{tier} {rank}" if rank else tier
        positions = user["preferred_positions"]
        pos_display = ", ".join(positions.split(",")) if positions else "미설정"
        total = user["wins"] + user["losses"]
        winrate = user["wins"] * 100 // max(total, 1)

        # 내전 ELO
        elo = await get_effective_elo(target.id)
        elo_display = f"{elo}"
        if user["elo_override"] is not None:
            elo_display += " (수동 보정)"

        embed = discord.Embed(
            title=f"📋 {target.display_name}의 프로필",
            color=discord.Color.blue(),
        )
        embed.add_field(name="소환사", value=f"**{user['riot_name']}#{user['riot_tag']}**", inline=False)
        embed.add_field(name="티어", value=f"{emoji} {rank_str}", inline=True)
        embed.add_field(name="레벨", value=str(user["level"]), inline=True)
        embed.add_field(name="솔랭 전적", value=f"{user['wins']}승 {user['losses']}패 (승률 {winrate}%)", inline=False)
        embed.add_field(name="내전 ELO", value=elo_display, inline=True)
        embed.add_field(name="선호 포지션", value=pos_display, inline=True)

        await interaction.response.send_message(embed=embed)

    # ── 전적 갱신 ──

    @app_commands.command(name="갱신", description="등록된 소환사 정보를 최신으로 갱신합니다")
    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user = await get_user(interaction.user.id)
        if not user:
            await interaction.followup.send("❌ 먼저 `/등록`으로 닉네임을 등록해주세요.")
            return

        profile = await fetch_full_profile(user["riot_name"], user["riot_tag"])
        if not profile:
            await interaction.followup.send("❌ Riot API 조회에 실패했습니다. 잠시 후 다시 시도해주세요.")
            return

        await update_user_stats(
            interaction.user.id,
            profile["tier"],
            profile["rank"],
            profile["wins"],
            profile["losses"],
            profile["level"],
        )

        emoji = TIER_EMOJI.get(profile["tier"], "")
        rank_str = f"{profile['tier']} {profile['rank']}" if profile["rank"] else profile["tier"]

        await interaction.followup.send(
            f"✅ 갱신 완료! {emoji} **{rank_str}** | "
            f"{profile['wins']}승 {profile['losses']}패"
        )

    # ── 선호 포지션 등록 ──

    @app_commands.command(name="포지션", description="선호 포지션을 등록합니다 (최대 2개)")
    @app_commands.describe(
        pos1="1순위 포지션",
        pos2="2순위 포지션 (선택)",
    )
    @app_commands.choices(pos1=POSITION_CHOICES, pos2=POSITION_CHOICES)
    async def position(
        self,
        interaction: discord.Interaction,
        pos1: app_commands.Choice[str],
        pos2: app_commands.Choice[str] = None,
    ):
        user = await get_user(interaction.user.id)
        if not user:
            await interaction.response.send_message("❌ 먼저 `/등록`으로 닉네임을 등록해주세요.")
            return

        positions = [pos1.value]
        if pos2 and pos2.value != pos1.value:
            positions.append(pos2.value)

        await set_positions(interaction.user.id, ",".join(positions))

        pos_names = {"TOP": "탑", "JUNGLE": "정글", "MID": "미드", "ADC": "원딜", "SUPPORT": "서포터"}
        display = ", ".join(pos_names[p] for p in positions)

        await interaction.response.send_message(f"✅ 선호 포지션이 **{display}**(으)로 설정되었습니다!")

    # ── 관리자 ELO 보정 ──

    @app_commands.command(name="elo보정", description="[관리자] 유저의 내전 ELO를 수동 보정합니다")
    @app_commands.describe(
        member="보정할 유저",
        elo="설정할 ELO 값 (0 입력 시 보정 해제)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def elo_override(self, interaction: discord.Interaction, member: discord.Member, elo: int):
        user = await get_user(member.id)
        if not user:
            await interaction.response.send_message("❌ 등록되지 않은 사용자입니다.", ephemeral=True)
            return

        if elo == 0:
            await set_elo_override(member.id, None)
            await interaction.response.send_message(f"✅ **{member.display_name}**의 ELO 수동 보정이 해제되었습니다.")
        else:
            await set_elo_override(member.id, elo)
            await interaction.response.send_message(f"✅ **{member.display_name}**의 내전 ELO가 **{elo}**으로 보정되었습니다.")

    @elo_override.error
    async def elo_override_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ 관리자 권한이 필요합니다.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Register(bot))
