import discord
from discord import app_commands
from discord.ext import commands

from utils.database import create_match, set_match_winner, get_user_record, get_recent_matches, get_user


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

        embed = discord.Embed(
            title=f"⚔️ {target.display_name}의 내전 전적",
            color=discord.Color.purple(),
        )
        embed.add_field(name="전적", value=f"**{wins}승 {losses}패** (총 {total}판)", inline=False)
        embed.add_field(name="승률", value=f"**{winrate}%**", inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="최근내전", description="최근 내전 기록을 확인합니다")
    async def recent_matches(self, interaction: discord.Interaction):
        matches = await get_recent_matches(10)

        if not matches:
            await interaction.response.send_message("📋 아직 기록된 내전이 없습니다.")
            return

        embed = discord.Embed(title="📋 최근 내전 기록", color=discord.Color.teal())

        for match in matches:
            winner = match["winner"]
            if winner:
                emoji = "🔵" if winner == "blue" else "🔴"
                result = f"{emoji} {'블루팀' if winner == 'blue' else '레드팀'} 승리"
            else:
                result = "⏳ 결과 미등록"

            embed.add_field(
                name=f"매치 #{match['match_id']}",
                value=f"{result}\n📅 {match['played_at'][:16]}",
                inline=True,
            )

        await interaction.response.send_message(embed=embed)


class SaveMatchView(discord.ui.View):
    """내전 결과 저장 뷰 - CustomGame에서 호출"""

    def __init__(self, blue_ids: list[int], red_ids: list[int]):
        super().__init__(timeout=3600)
        self.blue_ids = blue_ids
        self.red_ids = red_ids
        self.match_id: int | None = None

    @discord.ui.button(label="기록 저장", style=discord.ButtonStyle.green, emoji="💾")
    async def save_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.match_id:
            await interaction.response.send_message(f"이미 저장되었습니다! (매치 #{self.match_id})", ephemeral=True)
            return

        self.match_id = await create_match(self.blue_ids, self.red_ids, interaction.user.id)
        await interaction.response.send_message(
            f"💾 매치 **#{self.match_id}**로 저장되었습니다!\n"
            f"결과 등록: `/결과등록 {self.match_id} 블루팀/레드팀`"
        )

    @discord.ui.button(label="🔵 블루팀 승리", style=discord.ButtonStyle.blurple)
    async def blue_wins(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.match_id:
            self.match_id = await create_match(self.blue_ids, self.red_ids, interaction.user.id)

        await set_match_winner(self.match_id, "blue")
        await interaction.response.send_message(f"✅ 매치 #{self.match_id}: 🔵 **블루팀** 승리 기록 완료!")
        self.stop()

    @discord.ui.button(label="🔴 레드팀 승리", style=discord.ButtonStyle.red)
    async def red_wins(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.match_id:
            self.match_id = await create_match(self.blue_ids, self.red_ids, interaction.user.id)

        await set_match_winner(self.match_id, "red")
        await interaction.response.send_message(f"✅ 매치 #{self.match_id}: 🔴 **레드팀** 승리 기록 완료!")
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(Record(bot))
