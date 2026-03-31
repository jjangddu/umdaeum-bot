import random
import discord
from discord import app_commands
from discord.ext import commands

from utils.database import get_user, get_effective_elo, get_user_record, find_user_by_riot_id, create_match, set_match_winner
from utils.riot_api import tier_value, fetch_full_profile, TIER_EMOJI, get_position_score


class PositionSelect(discord.ui.Select):
    """포지션 선택 드롭다운"""

    def __init__(self, lobby_view: "LobbyView", user_data: dict, discord_id: int):
        options = [
            discord.SelectOption(label="탑", value="TOP", emoji="🛡️"),
            discord.SelectOption(label="정글", value="JUNGLE", emoji="🌿"),
            discord.SelectOption(label="미드", value="MID", emoji="⚡"),
            discord.SelectOption(label="원딜", value="ADC", emoji="🏹"),
            discord.SelectOption(label="서포터", value="SUPPORT", emoji="💚"),
            discord.SelectOption(label="상관없음", value="FILL", emoji="🔄"),
        ]
        super().__init__(
            placeholder="포지션을 선택하세요 (최대 2개)",
            min_values=1,
            max_values=2,
            options=options,
        )
        self.lobby_view = lobby_view
        self.user_data = user_data
        self.target_id = discord_id

    async def callback(self, interaction: discord.Interaction):
        selected = self.values
        if "FILL" in selected:
            positions = ""
        else:
            positions = ",".join(selected)

        self.user_data["positions"] = positions
        self.lobby_view.participants[self.target_id] = self.user_data

        await interaction.response.edit_message(
            content="✅ 참가 완료!", embed=None, view=None, delete_after=2,
        )
        # 로비 메시지 업데이트
        if self.lobby_view.message:
            await self.lobby_view.message.edit(
                embed=self.lobby_view.build_embed(), view=self.lobby_view
            )


class PositionSelectView(discord.ui.View):
    """포지션 선택 뷰 (ephemeral 메시지용)"""

    def __init__(self, lobby_view: "LobbyView", user_data: dict, discord_id: int):
        super().__init__(timeout=30)
        self.add_item(PositionSelect(lobby_view, user_data, discord_id))


class EstimatedTierSelect(discord.ui.Select):
    """언랭 유저용 예상 티어 선택"""

    def __init__(self, lobby_view: "LobbyView", user_data: dict, discord_id: int):
        options = [
            discord.SelectOption(label="아이언~브론즈", value="BRONZE_II"),
            discord.SelectOption(label="실버", value="SILVER_II"),
            discord.SelectOption(label="골드", value="GOLD_II"),
            discord.SelectOption(label="플래티넘", value="PLATINUM_II"),
            discord.SelectOption(label="에메랄드", value="EMERALD_II"),
            discord.SelectOption(label="다이아몬드", value="DIAMOND_IV"),
            discord.SelectOption(label="마스터+", value="MASTER_"),
        ]
        super().__init__(placeholder="예상 티어를 선택하세요", options=options)
        self.lobby_view = lobby_view
        self.user_data = user_data
        self.target_id = discord_id

    async def callback(self, interaction: discord.Interaction):
        parts = self.values[0].split("_")
        self.user_data["tier"] = parts[0]
        self.user_data["rank"] = parts[1] if parts[1] else ""

        # 이제 포지션 선택
        pos_view = PositionSelectView(self.lobby_view, self.user_data, self.target_id)
        await interaction.response.edit_message(
            content="📌 포지션을 선택하세요 (최대 2개):",
            view=pos_view,
        )


class EstimatedTierView(discord.ui.View):
    """언랭 예상 티어 선택 뷰"""

    def __init__(self, lobby_view: "LobbyView", user_data: dict, discord_id: int):
        super().__init__(timeout=30)
        self.add_item(EstimatedTierSelect(lobby_view, user_data, discord_id))


class JoinButton(discord.ui.Button):
    """내전 참가 버튼"""

    def __init__(self):
        super().__init__(label="참가", style=discord.ButtonStyle.green, emoji="✋")

    async def callback(self, interaction: discord.Interaction):
        view: LobbyView = self.view
        user = await get_user(interaction.user.id)
        if not user:
            await interaction.response.send_message("❌ 먼저 `/등록`으로 닉네임을 등록해주세요.", ephemeral=True)
            return

        if interaction.user.id in view.participants:
            await interaction.response.send_message("이미 참가 중입니다!", ephemeral=True)
            return

        elo = await get_effective_elo(interaction.user.id)
        record = await get_user_record(interaction.user.id)

        user_data = {
            "name": interaction.user.display_name,
            "riot": f"{user['riot_name']}#{user['riot_tag']}",
            "tier": user["tier"] or "UNRANKED",
            "rank": user["rank"] or "",
            "positions": "",
            "lp": user["lp"] if user["lp"] else 0,
            "elo": elo,
            "custom_wins": record["win"],
            "custom_losses": record["lose"],
        }

        # 언랭이면 예상 티어 먼저 선택
        if user_data["tier"] == "UNRANKED":
            tier_view = EstimatedTierView(view, user_data, interaction.user.id)
            await interaction.response.send_message(
                "🎯 랭크가 없습니다! 예상 티어를 선택해주세요:",
                view=tier_view,
                ephemeral=True,
            )
        else:
            # 포지션 선택
            pos_view = PositionSelectView(view, user_data, interaction.user.id)
            await interaction.response.send_message(
                "📌 포지션을 선택하세요 (최대 2개):",
                view=pos_view,
                ephemeral=True,
            )


class LeaveButton(discord.ui.Button):
    """내전 나가기 버튼"""

    def __init__(self):
        super().__init__(label="나가기", style=discord.ButtonStyle.red, emoji="🚪")

    async def callback(self, interaction: discord.Interaction):
        view: LobbyView = self.view
        if interaction.user.id not in view.participants:
            await interaction.response.send_message("참가 중이 아닙니다!", ephemeral=True)
            return

        del view.participants[interaction.user.id]
        # 파티에서도 제거
        for party in list(view.parties.values()):
            party.discard(interaction.user.id)

        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class PartyButton(discord.ui.Button):
    """같은 팀 파티 버튼"""

    def __init__(self):
        super().__init__(label="파티 묶기", style=discord.ButtonStyle.blurple, emoji="🔗")

    async def callback(self, interaction: discord.Interaction):
        view: LobbyView = self.view
        if interaction.user.id not in view.participants:
            await interaction.response.send_message("먼저 참가해주세요!", ephemeral=True)
            return

        # 파티 멤버 선택 모달
        await interaction.response.send_modal(PartyModal(view))


class PartyModal(discord.ui.Modal, title="파티 묶기"):
    partner = discord.ui.TextInput(
        label="같은 팀할 사람의 디스코드 이름 또는 @멘션",
        placeholder="예: 홍길동",
        required=True,
    )

    def __init__(self, view: "LobbyView"):
        super().__init__()
        self.lobby_view = view

    async def on_submit(self, interaction: discord.Interaction):
        partner_name = self.partner.value.strip().strip("@<>!")

        # 참가자 중에서 이름으로 찾기
        partner_id = None
        for pid, pinfo in self.lobby_view.participants.items():
            if partner_name.lower() in pinfo["name"].lower() or str(pid) == partner_name:
                partner_id = pid
                break

        if not partner_id:
            await interaction.response.send_message(
                "❌ 해당 사용자를 참가자 목록에서 찾을 수 없습니다.", ephemeral=True
            )
            return

        if partner_id == interaction.user.id:
            await interaction.response.send_message("❌ 본인은 파티에 추가할 수 없습니다.", ephemeral=True)
            return

        # 파티 생성/합류
        my_party = None
        partner_party = None
        for key, members in self.lobby_view.parties.items():
            if interaction.user.id in members:
                my_party = key
            if partner_id in members:
                partner_party = key

        if my_party and partner_party and my_party == partner_party:
            await interaction.response.send_message("이미 같은 파티입니다!", ephemeral=True)
            return

        if my_party:
            self.lobby_view.parties[my_party].add(partner_id)
            if partner_party:
                self.lobby_view.parties[my_party] |= self.lobby_view.parties.pop(partner_party)
        elif partner_party:
            self.lobby_view.parties[partner_party].add(interaction.user.id)
        else:
            party_key = interaction.user.id
            self.lobby_view.parties[party_key] = {interaction.user.id, partner_id}

        partner_name = self.lobby_view.participants[partner_id]["name"]
        await interaction.response.edit_message(embed=self.lobby_view.build_embed(), view=self.lobby_view)


class ForceJoinButton(discord.ui.Button):
    """관리자 강제 참가 버튼"""

    def __init__(self):
        super().__init__(label="강제참가", style=discord.ButtonStyle.gray, emoji="👑")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(ForceJoinModal(self.view))


class ForceJoinModal(discord.ui.Modal, title="강제 참가 (관리자)"):
    member_name = discord.ui.TextInput(
        label="디스코드 이름 또는 닉네임",
        placeholder="예: 홍길동",
        required=True,
    )

    def __init__(self, view: "LobbyView"):
        super().__init__()
        self.lobby_view = view

    async def on_submit(self, interaction: discord.Interaction):
        name = self.member_name.value.strip().strip("@<>!")

        # 서버 멤버 중에서 찾기
        guild = interaction.guild
        target = None
        for member in guild.members:
            if (name.lower() in member.display_name.lower()
                    or name.lower() in member.name.lower()
                    or str(member.id) == name):
                target = member
                break

        if not target:
            await interaction.response.send_message("❌ 서버에서 해당 유저를 찾을 수 없습니다.", ephemeral=True)
            return

        if target.id in self.lobby_view.participants:
            await interaction.response.send_message("이미 참가 중입니다!", ephemeral=True)
            return

        user = await get_user(target.id)
        if not user:
            await interaction.response.send_message(
                f"❌ **{target.display_name}**은(는) 등록되지 않은 유저입니다. `/대리등록`으로 먼저 등록해주세요.",
                ephemeral=True,
            )
            return

        elo = await get_effective_elo(target.id)
        record = await get_user_record(target.id)

        self.lobby_view.participants[target.id] = {
            "name": target.display_name,
            "riot": f"{user['riot_name']}#{user['riot_tag']}",
            "tier": user["tier"] or "UNRANKED",
            "rank": user["rank"] or "",
            "positions": user["preferred_positions"] or "",
            "lp": user["lp"] if user["lp"] else 0,
            "elo": elo,
            "custom_wins": record["win"],
            "custom_losses": record["lose"],
        }

        await interaction.response.edit_message(
            embed=self.lobby_view.build_embed(), view=self.lobby_view
        )


class GuestJoinButton(discord.ui.Button):
    """게스트 참가 버튼 (디스코드 미가입자)"""

    def __init__(self):
        super().__init__(label="게스트추가", style=discord.ButtonStyle.gray, emoji="👤")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(GuestJoinModal(self.view))


class GuestJoinModal(discord.ui.Modal, title="게스트 추가 (관리자)"):
    riot_id = discord.ui.TextInput(
        label="롤 닉네임#태그 (예: 오 노 아#0523)",
        placeholder="소환사이름#태그",
        required=True,
    )
    guest_tier = discord.ui.TextInput(
        label="티어 (예: GOLD II, DIAMOND IV) - 모르면 비워두세요",
        placeholder="예: GOLD II",
        required=False,
    )

    def __init__(self, view: "LobbyView"):
        super().__init__()
        self.lobby_view = view

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.riot_id.value.strip()
        if "#" not in raw:
            await interaction.response.send_message(
                "❌ `이름#태그` 형식으로 입력해주세요. (예: `오 노 아#0523`)", ephemeral=True
            )
            return

        name, tag = raw.rsplit("#", 1)
        name = name.strip()
        tag = tag.strip()

        # 이미 참가 중인지 확인 (riot id 기준)
        riot_full = f"{name}#{tag}".lower()
        for info in self.lobby_view.participants.values():
            if info["riot"].lower() == riot_full:
                await interaction.response.send_message("이미 참가 중입니다!", ephemeral=True)
                return

        # Riot API로 정보 조회 시도
        tier = "UNRANKED"
        rank = ""
        profile = await fetch_full_profile(name, tag)
        if profile:
            tier = profile["tier"]
            rank = profile["rank"]
            name = profile["name"]
            tag = profile["tag"]

        # 수동 티어 입력 처리
        if self.guest_tier.value.strip():
            parts = self.guest_tier.value.strip().upper().split()
            if parts:
                tier = parts[0]
            if len(parts) > 1:
                rank = parts[1]

        # 게스트는 음수 ID로 구분 (디스코드 유저와 충돌 방지)
        guest_id = -(len(self.lobby_view.participants) + 1000)

        self.lobby_view.participants[guest_id] = {
            "name": f"[게스트] {name}",
            "riot": f"{name}#{tag}",
            "tier": tier,
            "rank": rank,
            "positions": "",
            "lp": profile.get("lp", 0) if profile else 0,
            "elo": 1000,
            "custom_wins": 0,
            "custom_losses": 0,
            "is_guest": True,
        }

        await interaction.response.edit_message(
            embed=self.lobby_view.build_embed(), view=self.lobby_view
        )


class StartButton(discord.ui.Button):
    """팀 짜기 시작 버튼"""

    def __init__(self):
        super().__init__(label="팀 짜기!", style=discord.ButtonStyle.green, emoji="⚔️")

    async def callback(self, interaction: discord.Interaction):
        view: LobbyView = self.view

        if len(view.participants) < 2:
            await interaction.response.send_message("❌ 최소 2명이 필요합니다!", ephemeral=True)
            return

        if len(view.participants) > 10:
            await interaction.response.send_message("❌ 최대 10명까지 가능합니다!", ephemeral=True)
            return

        blue, red = balance_teams(view.participants, view.parties)

        embed = build_team_embed(view.participants, blue, red, "⚔️ 내전 팀 구성 완료!")

        # 파티 표시
        party_info = []
        for members in view.parties.values():
            if len(members) > 1:
                names = [view.participants[m]["name"] for m in members if m in view.participants]
                if names:
                    party_info.append(f"🔗 {', '.join(names)}")
        if party_info:
            embed.add_field(name="파티", value="\n".join(party_info), inline=False)

        embed.set_footer(text="코인 토스: /코인토스 로 블루/레드 사이드를 결정하세요!")

        # 결과 저장 (나중에 record cog에서 사용)
        view.last_blue = blue
        view.last_red = red

        await interaction.response.edit_message(embed=embed, view=ResultView(view))


class ResultView(discord.ui.View):
    """팀 구성 결과 뷰"""

    def __init__(self, lobby_view: "LobbyView"):
        super().__init__(timeout=7200)  # 2시간 타임아웃
        self.lobby_view = lobby_view
        self.match_id: int | None = None

    @discord.ui.button(label="다시 섞기", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def reshuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = self.lobby_view
        blue, red = balance_teams(view.participants, view.parties)
        view.last_blue = blue
        view.last_red = red

        embed = build_team_embed(view.participants, blue, red, "⚔️ 내전 팀 구성 완료! (재배치)")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="코인 토스", style=discord.ButtonStyle.blurple, emoji="🪙", row=0)
    async def coin_toss(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = random.choice(["🔵 블루 사이드", "🔴 레드 사이드"])
        await interaction.response.send_message(f"🪙 **코인 토스 결과:** 1팀이 **{side}**입니다!")

    @discord.ui.button(label="🔵 블루팀 승리", style=discord.ButtonStyle.blurple, row=1)
    async def blue_wins(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._record_result(interaction, "blue")

    @discord.ui.button(label="🔴 레드팀 승리", style=discord.ButtonStyle.red, row=1)
    async def red_wins(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._record_result(interaction, "red")

    @discord.ui.button(label="한판 더!", style=discord.ButtonStyle.green, emoji="🔁", row=2)
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = self.lobby_view
        # 기존 참가자 유지, 파티 유지, 새로운 로비로 복귀
        new_view = LobbyView()
        new_view.participants = view.participants.copy()
        new_view.parties = {k: v.copy() for k, v in view.parties.items()}

        embed = new_view.build_embed()
        embed.title = "🔁 한판 더! 내전 모집중!"
        await interaction.response.edit_message(embed=embed, view=new_view)
        new_view.message = interaction.message

    @discord.ui.button(label="내전 종료", style=discord.ButtonStyle.gray, emoji="🏁", row=2)
    async def end_session(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🏁 내전 종료!",
            description="수고하셨습니다! GG!",
            color=discord.Color.dark_gray(),
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def _record_result(self, interaction: discord.Interaction, winner: str):
        view = self.lobby_view
        blue = view.last_blue
        red = view.last_red

        if not blue or not red:
            await interaction.response.send_message("❌ 팀 정보가 없습니다.", ephemeral=True)
            return

        if self.match_id is not None:
            await interaction.response.send_message(
                f"❌ 이미 매치 #{self.match_id}에 결과가 등록되었습니다.", ephemeral=True
            )
            return

        # 게스트(음수 ID)는 DB 저장에서 제외
        db_blue = [uid for uid in blue if uid > 0]
        db_red = [uid for uid in red if uid > 0]

        if db_blue or db_red:
            self.match_id = await create_match(db_blue, db_red, interaction.user.id)
            await set_match_winner(self.match_id, winner)

        emoji = "🔵" if winner == "blue" else "🔴"
        team_name = "블루팀" if winner == "blue" else "레드팀"

        # 결과 버튼 비활성화
        self.blue_wins.disabled = True
        self.red_wins.disabled = True

        # 현재 embed에 결과 추가
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.blue() if winner == "blue" else discord.Color.red()
        embed.set_footer(text=f"{emoji} {team_name} 승리! | 매치 #{self.match_id or 'N/A'}")

        await interaction.response.edit_message(embed=embed, view=self)


class LobbyView(discord.ui.View):
    """내전 로비 뷰"""

    def __init__(self):
        super().__init__(timeout=1800)  # 30분 타임아웃
        self.participants: dict[int, dict] = {}  # discord_id -> info
        self.parties: dict[int, set[int]] = {}  # party_leader -> set of member ids
        self.last_blue: list[int] = []
        self.last_red: list[int] = []
        self.message: discord.Message | None = None  # 로비 메시지 참조
        self.add_item(JoinButton())
        self.add_item(LeaveButton())
        self.add_item(PartyButton())
        self.add_item(ForceJoinButton())
        self.add_item(GuestJoinButton())
        self.add_item(StartButton())

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⚔️ 엄대엄 내전 모집중!",
            description=f"참가자: **{len(self.participants)}/10**명\n참가하려면 아래 버튼을 눌러주세요!",
            color=discord.Color.orange(),
        )

        if self.participants:
            lines = []
            for uid, info in self.participants.items():
                tier_str = f"{info['tier']} {info['rank']}".strip()
                # 파티 표시
                party_mark = ""
                for party_members in self.parties.values():
                    if uid in party_members and len(party_members) > 1:
                        party_mark = " 🔗"
                        break
                pos = ", ".join(POS_NAMES.get(x, x) for x in info.get("positions", "").split(",") if x)
                pos_str = f" [{pos}]" if pos else " [상관없음]"
                lines.append(f"**{info['name']}** - {tier_str}{pos_str}{party_mark}")

            embed.add_field(name="참가자 목록", value="\n".join(lines), inline=False)

        # 파티 정보
        party_info = []
        for members in self.parties.values():
            if len(members) > 1:
                names = [self.participants[m]["name"] for m in members if m in self.participants]
                if names:
                    party_info.append(f"🔗 {', '.join(names)}")
        if party_info:
            embed.add_field(name="파티", value="\n".join(party_info), inline=False)

        embed.set_footer(text="🔗 같은 PC방이면 '파티 묶기'로 같은 팀 배정!")
        return embed


POS_NAMES = {"TOP": "탑", "JUNGLE": "정글", "MID": "미드", "ADC": "원딜", "SUPPORT": "서폿"}


def format_team(participants: dict, team_ids: list[int]) -> str:
    lines = []
    for uid in team_ids:
        p = participants[uid]
        tier_str = f"{p['tier']} {p['rank']}".strip()
        preferred = [x for x in p["positions"].split(",") if x]
        pos_display = ", ".join(POS_NAMES.get(x, x) for x in preferred) if preferred else "상관없음"
        mmr = get_mmr(p)
        lines.append(f"**{p['name']}** ({p['riot']}) - {tier_str} [{pos_display}] | 점수 {mmr:.1f}")
    return "\n".join(lines) or "없음"


def build_team_embed(participants: dict, blue: list[int], red: list[int], title: str) -> discord.Embed:
    blue_total = sum(get_mmr(participants[uid]) for uid in blue)
    red_total = sum(get_mmr(participants[uid]) for uid in red)
    blue_avg = blue_total / max(len(blue), 1)
    red_avg = red_total / max(len(red), 1)

    embed = discord.Embed(title=title, color=discord.Color.gold())
    embed.add_field(
        name=f"🔵 블루팀 (합계: {blue_total:.1f} | 평균: {blue_avg:.1f})",
        value=format_team(participants, blue),
        inline=False,
    )
    embed.add_field(
        name=f"🔴 레드팀 (합계: {red_total:.1f} | 평균: {red_avg:.1f})",
        value=format_team(participants, red),
        inline=False,
    )
    diff = abs(blue_total - red_total)
    if diff < 3:
        embed.set_footer(text=f"✅ 밸런스 좋음! (점수 차이: {diff:.1f})")
    elif diff < 8:
        embed.set_footer(text=f"⚠️ 밸런스 보통 (점수 차이: {diff:.1f})")
    else:
        embed.set_footer(text=f"❌ 밸런스 차이 큼 (점수 차이: {diff:.1f}) - 다시 섞기를 추천합니다")
    return embed


# 비선호 라인 보정: 선호 포지션이 아닌 라인을 갈 경우 점수를 이만큼 차감
# → 그 사람이 있는 팀에 약간의 보상(더 강한 팀원 배정)을 주는 효과
OFF_ROLE_PENALTY = 2.0


def get_mmr(p: dict, assigned_position: str = None) -> float:
    """대회 점수표 기반 MMR 계산
    - 선호 포지션이 있으면 해당 포지션 점수 사용 (여러 개면 평균)
    - 없으면 전 포지션 평균
    - assigned_position이 주어지면 해당 포지션으로 계산 + 비선호 시 페널티
    - 내전 판수가 쌓이면 내전 ELO 비중 증가 (최대 50%)
    """
    tier = p["tier"]
    rank = p["rank"]
    lp = p.get("lp", 0)
    positions = [x for x in p.get("positions", "").split(",") if x]

    # 포지션별 점수 계산
    if assigned_position:
        solo_score = get_position_score(tier, rank, assigned_position, lp)
        # 비선호 라인이면 페널티 (팀에 보상 효과)
        if positions and assigned_position not in positions:
            solo_score -= OFF_ROLE_PENALTY
    elif positions:
        solo_score = sum(get_position_score(tier, rank, pos, lp) for pos in positions) / len(positions)
    else:
        all_pos = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]
        solo_score = sum(get_position_score(tier, rank, pos, lp) for pos in all_pos) / 5

    # 내전 ELO 혼합
    custom_elo = p.get("elo", 1000)
    custom_games = p.get("custom_wins", 0) + p.get("custom_losses", 0)

    # 내전 판수에 따라 비중 조정 (20판이면 50% 내전 ELO)
    # 내전 ELO를 점수표 스케일로 정규화 (1000 ELO ≈ 30점)
    normalized_elo = custom_elo / 1000 * 30

    custom_weight = min(custom_games / 20, 1.0) * 0.5
    solo_weight = 1.0 - custom_weight

    return solo_score * solo_weight + normalized_elo * custom_weight


def balance_teams(
    participants: dict[int, dict],
    parties: dict[int, set[int]],
) -> tuple[list[int], list[int]]:
    """MMR 기반 밸런스 팀 분배 - 모든 조합 탐색으로 최적 매칭"""
    from itertools import combinations

    all_ids = list(participants.keys())
    n = len(all_ids)
    half = n // 2

    # 파티 그룹 구성 (같은 팀 유지해야 하는 멤버들)
    party_groups = []  # list of sets
    assigned = set()
    for members in parties.values():
        active = frozenset(m for m in members if m in participants and m not in assigned)
        if len(active) > 1:
            party_groups.append(active)
            assigned.update(active)

    # 개인 플레이어
    solo_ids = [uid for uid in all_ids if uid not in assigned]

    # 유효한 팀 조합 생성 (파티 제약 만족)
    best_blue, best_diff = None, float("inf")

    # 파티가 있으면 각 파티를 blue 또는 red에 배치하는 조합 시도
    # 파티 수가 적으므로 (최대 5개) 2^5 = 32가지
    party_count = len(party_groups)

    for party_mask in range(1 << party_count):
        blue_forced = set()
        red_forced = set()

        for i, group in enumerate(party_groups):
            if party_mask & (1 << i):
                blue_forced.update(group)
            else:
                red_forced.update(group)

        # 팀 사이즈 체크
        if len(blue_forced) > half or len(red_forced) > n - half:
            continue

        # 나머지 솔로 플레이어 중에서 블루팀에 추가할 인원 선택
        need_blue = half - len(blue_forced)
        if need_blue < 0:
            continue

        # 솔로 플레이어 조합 탐색 (최대 C(8,4) = 70가지)
        for solo_blue in combinations(solo_ids, min(need_blue, len(solo_ids))):
            blue_team = list(blue_forced) + list(solo_blue)
            red_team = [uid for uid in all_ids if uid not in blue_team]

            if len(blue_team) != half:
                continue

            blue_mmr = sum(get_mmr(participants[uid]) for uid in blue_team)
            red_mmr = sum(get_mmr(participants[uid]) for uid in red_team)
            diff = abs(blue_mmr - red_mmr)

            if diff < best_diff:
                best_diff = diff
                best_blue = blue_team

    if best_blue is None:
        # fallback: 랜덤
        random.shuffle(all_ids)
        best_blue = all_ids[:half]

    best_red = [uid for uid in all_ids if uid not in best_blue]
    return best_blue, best_red


class CustomGame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="내전", description="내전 모집을 시작합니다")
    async def start_lobby(self, interaction: discord.Interaction):
        view = LobbyView()
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="코인토스", description="블루/레드 사이드를 랜덤으로 결정합니다")
    async def coin_toss(self, interaction: discord.Interaction):
        result = random.choice(["블루", "레드"])
        color = discord.Color.blue() if result == "블루" else discord.Color.red()
        emoji = "🔵" if result == "블루" else "🔴"

        embed = discord.Embed(
            title="🪙 코인 토스!",
            description=f"\n{emoji} **{result} 사이드**가 선택되었습니다!",
            color=color,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomGame(bot))
