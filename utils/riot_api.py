import aiohttp
import os

RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")

# 한국 서버 기준
ASIA_BASE = "https://asia.api.riotgames.com"
KR_BASE = "https://kr.api.riotgames.com"

TIER_EMOJI = {
    "IRON": "🔩",
    "BRONZE": "🥉",
    "SILVER": "🥈",
    "GOLD": "🥇",
    "PLATINUM": "💎",
    "EMERALD": "🟢",
    "DIAMOND": "💠",
    "MASTER": "🏅",
    "GRANDMASTER": "🎖️",
    "CHALLENGER": "🏆",
}

TIER_ORDER = {
    "IRON": 0, "BRONZE": 1, "SILVER": 2, "GOLD": 3,
    "PLATINUM": 4, "EMERALD": 5, "DIAMOND": 6,
    "MASTER": 7, "GRANDMASTER": 8, "CHALLENGER": 9,
}

RANK_ORDER = {"IV": 0, "III": 1, "II": 2, "I": 3}


def tier_value(tier: str, rank: str) -> int:
    """티어를 숫자로 변환 (단순 비교용)"""
    return TIER_ORDER.get(tier, 0) * 4 + RANK_ORDER.get(rank, 0)


# ── 대회 기준 포지션별 점수표 ──
# 키: (tier, rank), 값: {"TOP": x, "JUNGLE": x, "MID": x, "ADC": x, "SUPPORT": x}
# 마스터 이상은 LP 구간별로 별도 처리

POSITION_SCORE_TABLE = {
    # 실버3 이하 (아이언, 브론즈, 실버4, 실버3)
    ("SILVER", "III"):  {"TOP": 11, "JUNGLE": 10, "MID": 13, "ADC": 10, "SUPPORT": 15},
    ("SILVER", "II"):   {"TOP": 12, "JUNGLE": 11, "MID": 13.9, "ADC": 10.6, "SUPPORT": 15.9},
    ("SILVER", "I"):    {"TOP": 13, "JUNGLE": 11.9, "MID": 14.8, "ADC": 11.3, "SUPPORT": 16.7},
    ("GOLD", "IV"):     {"TOP": 14.6, "JUNGLE": 12.8, "MID": 15.9, "ADC": 11.9, "SUPPORT": 17.6},
    ("GOLD", "III"):    {"TOP": 15.9, "JUNGLE": 13.8, "MID": 16.8, "ADC": 12.6, "SUPPORT": 18.3},
    ("GOLD", "II"):     {"TOP": 17.7, "JUNGLE": 14.7, "MID": 17.8, "ADC": 13.4, "SUPPORT": 19.1},
    ("GOLD", "I"):      {"TOP": 19, "JUNGLE": 16.7, "MID": 19.7, "ADC": 15.1, "SUPPORT": 20.5},
    ("PLATINUM", "IV"): {"TOP": 21.2, "JUNGLE": 18.1, "MID": 21.1, "ADC": 16.4, "SUPPORT": 21.2},
    ("PLATINUM", "III"):{"TOP": 24, "JUNGLE": 19.3, "MID": 22.7, "ADC": 17.5, "SUPPORT": 22},
    ("PLATINUM", "II"): {"TOP": 24.7, "JUNGLE": 20.5, "MID": 24.3, "ADC": 18.7, "SUPPORT": 22.8},
    ("PLATINUM", "I"):  {"TOP": 25.2, "JUNGLE": 21.9, "MID": 27.1, "ADC": 20.3, "SUPPORT": 24.2},
    ("EMERALD", "IV"):  {"TOP": 26, "JUNGLE": 23.4, "MID": 29.6, "ADC": 21.6, "SUPPORT": 25.1},
    ("EMERALD", "III"): {"TOP": 26.5, "JUNGLE": 24.8, "MID": 31.8, "ADC": 22.8, "SUPPORT": 26},
    ("EMERALD", "II"):  {"TOP": 27.3, "JUNGLE": 26.6, "MID": 33, "ADC": 24.3, "SUPPORT": 27},
    ("EMERALD", "I"):   {"TOP": 28.6, "JUNGLE": 28.8, "MID": 34.6, "ADC": 25.7, "SUPPORT": 28.2},
    ("DIAMOND", "IV"):  {"TOP": 30.3, "JUNGLE": 30.7, "MID": 35.4, "ADC": 27.6, "SUPPORT": 29.3},
    ("DIAMOND", "III"): {"TOP": 31.6, "JUNGLE": 32.5, "MID": 37.1, "ADC": 29.7, "SUPPORT": 30.3},
    ("DIAMOND", "II"):  {"TOP": 33.8, "JUNGLE": 34.8, "MID": 37.1, "ADC": 32.1, "SUPPORT": 31.3},
    ("DIAMOND", "I"):   {"TOP": 35.7, "JUNGLE": 36.8, "MID": 38, "ADC": 34, "SUPPORT": 32.2},
}

# 마스터/그마/챌 LP 구간별 점수
MASTER_SCORE_TABLE = [
    # (lp_min, lp_max, scores)
    (0,    99,   {"TOP": 37.4, "JUNGLE": 38.2, "MID": 39.8, "ADC": 36.1, "SUPPORT": 33.1}),
    (100,  199,  {"TOP": 39.1, "JUNGLE": 39.4, "MID": 41.3, "ADC": 38.3, "SUPPORT": 34}),
    (200,  299,  {"TOP": 41.8, "JUNGLE": 40.6, "MID": 43, "ADC": 40.6, "SUPPORT": 35}),
    (300,  399,  {"TOP": 43, "JUNGLE": 42.4, "MID": 44.7, "ADC": 43.5, "SUPPORT": 36.1}),
    (400,  499,  {"TOP": 45.2, "JUNGLE": 44.3, "MID": 45.2, "ADC": 46.2, "SUPPORT": 37.7}),
    (500,  599,  {"TOP": 47.9, "JUNGLE": 46.3, "MID": 46.2, "ADC": 48.6, "SUPPORT": 39}),
    (600,  699,  {"TOP": 49.7, "JUNGLE": 48.4, "MID": 48, "ADC": 51.1, "SUPPORT": 41.1}),
    (700,  799,  {"TOP": 51.3, "JUNGLE": 50.6, "MID": 49.3, "ADC": 53.7, "SUPPORT": 42.8}),
    (800,  899,  {"TOP": 52.6, "JUNGLE": 53.1, "MID": 50.2, "ADC": 56.1, "SUPPORT": 44.5}),
    (900,  999,  {"TOP": 54.8, "JUNGLE": 55.4, "MID": 51.4, "ADC": 58.8, "SUPPORT": 46.2}),
    (1000, 1099, {"TOP": 57.8, "JUNGLE": 57.7, "MID": 53.1, "ADC": 61.3, "SUPPORT": 48}),
    (1100, 1199, {"TOP": 59.9, "JUNGLE": 59.4, "MID": 54.7, "ADC": 62.2, "SUPPORT": 48.7}),
    (1200, 1299, {"TOP": 62.4, "JUNGLE": 60.5, "MID": 56, "ADC": 62.7, "SUPPORT": 49.3}),
    (1300, 1399, {"TOP": 63.1, "JUNGLE": 61.3, "MID": 57.3, "ADC": 63.3, "SUPPORT": 49.8}),
    (1400, 1499, {"TOP": 63.8, "JUNGLE": 62.2, "MID": 58.2, "ADC": 63.9, "SUPPORT": 50.1}),
    (1500, 1599, {"TOP": 64.6, "JUNGLE": 63.3, "MID": 59.9, "ADC": 64.2, "SUPPORT": 50.6}),
    (1600, 1699, {"TOP": 65.5, "JUNGLE": 63.8, "MID": 60.8, "ADC": 64.4, "SUPPORT": 50.9}),
    (1700, 1799, {"TOP": 66, "JUNGLE": 64.3, "MID": 61.1, "ADC": 64.7, "SUPPORT": 51.5}),
    (1800, 9999, {"TOP": 67, "JUNGLE": 66, "MID": 62, "ADC": 65, "SUPPORT": 52}),
]

# 아이언/브론즈는 실버3 이하와 동일
_LOW_TIER_SCORE = {"TOP": 11, "JUNGLE": 10, "MID": 13, "ADC": 10, "SUPPORT": 15}


def get_position_score(tier: str, rank: str, position: str, lp: int = 0) -> float:
    """티어 + 포지션 기반 대회 점수 반환"""
    tier = tier.upper()
    position = position.upper()

    # 언랭크 / 아이언 / 브론즈 → 최저 점수
    if tier in ("UNRANKED", "IRON", "BRONZE"):
        return _LOW_TIER_SCORE.get(position, 11)

    # 실버4 이하
    if tier == "SILVER" and rank in ("IV", ""):
        return _LOW_TIER_SCORE.get(position, 11)

    # 마스터/그마/챌
    if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        for lp_min, lp_max, scores in MASTER_SCORE_TABLE:
            if lp_min <= lp <= lp_max:
                return scores.get(position, 40)
        return MASTER_SCORE_TABLE[-1][2].get(position, 52)

    # 일반 티어 (실버3 ~ 다이아1)
    key = (tier, rank)
    if key in POSITION_SCORE_TABLE:
        return POSITION_SCORE_TABLE[key].get(position, 20)

    # 매칭 안 되면 단순 계산 fallback
    return tier_value(tier, rank) * 1.5 + 10


async def get_account_by_riot_id(name: str, tag: str) -> dict | None:
    """Riot ID로 계정 정보 조회"""
    url = f"{ASIA_BASE}/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_summoner_by_puuid(puuid: str) -> dict | None:
    """PUUID로 소환사 정보 조회"""
    url = f"{KR_BASE}/lol/summoner/v4/summoners/by-puuid/{puuid}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_ranked_stats(puuid: str) -> dict | None:
    """소환사 랭크 정보 조회 (PUUID 기반)"""
    url = f"{KR_BASE}/lol/league/v4/entries/by-puuid/{puuid}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                entries = await resp.json()
                for entry in entries:
                    if entry["queueType"] == "RANKED_SOLO_5x5":
                        return entry
                return None
            return None


async def fetch_full_profile(name: str, tag: str) -> dict | None:
    """Riot ID로 전체 프로필 조회 (계정 + 소환사 + 랭크)"""
    account = await get_account_by_riot_id(name, tag)
    if not account:
        return None

    summoner = await get_summoner_by_puuid(account["puuid"])
    if not summoner:
        return None

    ranked = await get_ranked_stats(account["puuid"])

    return {
        "puuid": account["puuid"],
        "name": account.get("gameName", name),
        "tag": account.get("tagLine", tag),
        "level": summoner.get("summonerLevel", 0),
        "tier": ranked["tier"] if ranked else "UNRANKED",
        "rank": ranked["rank"] if ranked else "",
        "wins": ranked["wins"] if ranked else 0,
        "losses": ranked["losses"] if ranked else 0,
        "lp": ranked.get("leaguePoints", 0) if ranked else 0,
    }
