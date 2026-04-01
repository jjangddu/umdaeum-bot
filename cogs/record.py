import discord
from discord import app_commands
from discord.ext import commands

from utils.database import (
    create_match, set_match_winner, get_user_record,
    get_recent_matches, get_user, get_effective_elo,
)


async def _resolve_name(bot: commands.Bot, guild: discord.Guild, discord_id: int) -> str:
    """discord_id로 표시 이름 가져오기 (서버 닉네임 > riot 이름 > ID)"""
    member = guild.get_member(discord_id)
    if member:
        return member.display_name
    user = await get_user(discord_id)
    if user:
        return f"{user['riot_name']}"
    return str(discord_id)


class Record(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="결과등록", description="내전 결과를 등록합니다")
    @app_commands.describe(
        match_id="매치 ID",
        winner="승리 팀",
    )
    @app_commands.choices(winner=[
        app_commands.Choice(name="블루팀 승리", value="blue"),
        app_commands.Choice(name="레드팀 승리", value="red"),
    ])
    async def record_result(
        self,
        interaction: discord.Interaction,
        match_id: int,
        winner: app_commands.Choice[str],
    ):
        await set_match_winner(match_id, winner.value)

        emoji = "🔵" if winner.value == "blue" else "🔴"
        team_name = "블루팀" if winner.value == "blue" else "레드팀"

        embed = discord.Embed(
            title="✅ 결과 등록 완료!",
            description=f"매치 #{match_id}: {emoji} **{team_name}** 승리!",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="내전전적", description="내전 전적을 확인합니다")
    @app_commands.describe(member="조회할 사용자 (비워두면 본인)")
    async def match_record(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        user = await get_user(target.id)

        if not user:
            await interaction.response.send_message("❌ 등록되지 않은 사용자입니다.")
            return

        record = await get_user_record(target.id)
        wins = record["win"]
        losses = record["lose"]
        total = wins + losses
        winrate = wins * 100 // max(total, 1)
        elo = await get_effective_elo(target.id)

        embed = discord.Embed(
            title=f"⚔️ {target.display_name}의 내전 전적",
            color=discord.Color.purple(),
        )
        embed.add_field(name="전적", value=f"**{wins}승 {losses}패** (총 {total}판)", inline=True)
        embed.add_field(name="승률", value=f"**{winrate}%**", inline=True)
        embed.add_field(name="내전 ELO", value=f"**{elo}**", inline=True)

        # 최근 5경기 기록
        from utils.database import get_db
        import aiosqlite
        db = await get_db()
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT mr.match_id, mr.team, mr.result, m.played_at, m.blue_team, m.red_team
               FROM match_records mr
               JOIN matches m ON mr.match_id = m.match_id
               WHERE mr.discord_id=? AND mr.result IS NOT NULL
               ORDER BY mr.match_id DESC LIMIT 5""",
            (target.id,),
        )
        recent = await cursor.fetchall()
        await db.close()

        if recent:
            history_lines = []
            for r in recent:
                emoji = "✅" if r["result"] == "win" else "❌"
                team_emoji = "🔵" if r["team"] == "blue" else "🔴"
                date = r["played_at"][:10] if r["played_at"] else ""

                # 같은 팀 멤버 이름
                if r["team"] == "blue":
                    team_ids = [int(x) for x in r["blue_team"].split(",")]
                else:
                    team_ids = [int(x) for x in r["red_team"].split(",")]
                teammates = []
                for tid in team_ids:
                    if tid != target.id:
                        name = await _resolve_name(self.bot, interaction.guild, tid)
                        teammates.append(name)
                team_str = ", ".join(teammates[:4]) if teammates else ""

                history_lines.append(
                    f"{emoji} 매치#{r['match_id']} {team_emoji} {'승' if r['result'] == 'win' else '패'}"
                    f" | {team_str} | {date}"
                )
            embed.add_field(name="최근 경기", value="\n".join(history_lines), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="최근내전", description="최근 내전 기록을 확인합니다")
    async def recent_matches(self, interaction: discord.Interaction):
        await interaction.response.defer()

        matches = await get_recent_matches(10)

        if not matches:
            await interaction.followup.send("📋 아직 기록된 내전이 없습니다.")
            return

        embed = discord.Embed(title="📋 최근 내전 기록", color=discord.Color.teal())

        for match in matches:
            winner = match["winner"]
            if winner:
                emoji = "🔵" if winner == "blue" else "🔴"
                result_str = f"{emoji} {'블루팀' if winner == 'blue' else '레드팀'} 승리"
            else:
                result_str = "⏳ 결과 미등록"

            # 팀 멤버 이름 표시
            blue_ids = [int(x) for x in match["blue_team"].split(",") if x]
            red_ids = [int(x) for x in match["red_team"].split(",") if x]

            blue_names = []
            for uid in blue_ids:
                name = await _resolve_name(self.bot, interaction.guild, uid)
                mark = " ✅" if winner == "blue" else " ❌" if winner == "red" else ""
                blue_names.append(f"{name}{mark}")

            red_names = []
            for uid in red_ids:
                name = await _resolve_name(self.bot, interaction.guild, uid)
                mark = " ✅" if winner == "red" else " ❌" if winner == "blue" else ""
                red_names.append(f"{name}{mark}")

            date = match["played_at"][:16] if match["played_at"] else ""

            value = (
                f"{result_str}\n"
                f"🔵 {', '.join(blue_names)}\n"
                f"🔴 {', '.join(red_names)}\n"
                f"📅 {date}"
            )

            embed.add_field(
                name=f"매치 #{match['match_id']}",
                value=value,
                inline=False,
            )

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Record(bot))
