import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "umdaeum.db")

# 내전 ELO 기본값
DEFAULT_ELO = 1000
ELO_K = 32  # ELO 변동 계수


async def init_db():
    """데이터베이스 초기화 및 테이블 생성"""
    async with aiosqlite.connect(DB_PATH) as db:
        # 사용자 등록 테이블
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id INTEGER PRIMARY KEY,
                riot_name TEXT NOT NULL,
                riot_tag TEXT NOT NULL,
                tier TEXT,
                rank TEXT,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                preferred_positions TEXT DEFAULT '',
                lp INTEGER DEFAULT 0,
                custom_elo INTEGER DEFAULT 1000,
                elo_override INTEGER,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 기존 테이블에 컬럼 추가 (이미 존재하면 무시)
        for col, default in [("custom_elo", "1000"), ("elo_override", "NULL"), ("lp", "0")]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT {default}")
            except Exception:
                pass

        # 내전 기록 테이블
        await db.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                match_id INTEGER PRIMARY KEY AUTOINCREMENT,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                blue_team TEXT NOT NULL,
                red_team TEXT NOT NULL,
                winner TEXT,
                recorded_by INTEGER
            )
        """)

        # 개인 내전 전적 테이블
        await db.execute("""
            CREATE TABLE IF NOT EXISTS match_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                discord_id INTEGER NOT NULL,
                team TEXT NOT NULL,
                result TEXT,
                FOREIGN KEY (match_id) REFERENCES matches(match_id),
                FOREIGN KEY (discord_id) REFERENCES users(discord_id)
            )
        """)

        await db.commit()


async def get_db():
    """데이터베이스 연결 반환"""
    return await aiosqlite.connect(DB_PATH)


# ── 사용자 관련 ──

async def register_user(discord_id: int, riot_name: str, riot_tag: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (discord_id, riot_name, riot_tag) VALUES (?, ?, ?)",
            (discord_id, riot_name, riot_tag),
        )
        await db.commit()


async def find_user_by_riot_id(riot_name: str, riot_tag: str):
    """Riot ID로 이미 등록된 유저 찾기"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE LOWER(riot_name)=LOWER(?) AND LOWER(riot_tag)=LOWER(?)",
            (riot_name, riot_tag),
        )
        return await cursor.fetchone()


async def update_user_stats(discord_id: int, tier: str, rank: str, wins: int, losses: int, level: int, lp: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET tier=?, rank=?, wins=?, losses=?, level=?, lp=? WHERE discord_id=?",
            (tier, rank, wins, losses, level, lp, discord_id),
        )
        await db.commit()


async def set_estimated_tier(discord_id: int, tier: str, rank: str):
    """언랭 유저의 예상 티어 설정"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET tier=?, rank=? WHERE discord_id=?",
            (tier, rank, discord_id),
        )
        await db.commit()


async def get_user(discord_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE discord_id=?", (discord_id,))
        return await cursor.fetchone()


async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users")
        return await cursor.fetchall()


async def set_positions(discord_id: int, positions: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET preferred_positions=? WHERE discord_id=?",
            (positions, discord_id),
        )
        await db.commit()


# ── ELO 관련 ──

async def get_effective_elo(discord_id: int) -> int:
    """유저의 유효 ELO 반환 (수동 보정 > 자체 ELO)"""
    user = await get_user(discord_id)
    if not user:
        return DEFAULT_ELO
    if user["elo_override"] is not None:
        return user["elo_override"]
    return user["custom_elo"] or DEFAULT_ELO


async def set_elo_override(discord_id: int, elo: int | None):
    """관리자가 수동으로 ELO 보정"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET elo_override=? WHERE discord_id=?",
            (elo, discord_id),
        )
        await db.commit()


async def update_elo_after_match(winners: list[int], losers: list[int]):
    """내전 결과에 따라 ELO 업데이트"""
    # 팀 평균 ELO 계산
    winner_elos = [await get_effective_elo(uid) for uid in winners]
    loser_elos = [await get_effective_elo(uid) for uid in losers]

    avg_winner = sum(winner_elos) / max(len(winner_elos), 1)
    avg_loser = sum(loser_elos) / max(len(loser_elos), 1)

    # 기대 승률 계산
    expected_win = 1 / (1 + 10 ** ((avg_loser - avg_winner) / 400))
    expected_lose = 1 - expected_win

    async with aiosqlite.connect(DB_PATH) as db:
        for uid in winners:
            user = await get_user(uid)
            current = user["custom_elo"] or DEFAULT_ELO
            new_elo = round(current + ELO_K * (1 - expected_win))
            await db.execute("UPDATE users SET custom_elo=? WHERE discord_id=?", (new_elo, uid))

        for uid in losers:
            user = await get_user(uid)
            current = user["custom_elo"] or DEFAULT_ELO
            new_elo = round(current + ELO_K * (0 - expected_lose))
            await db.execute("UPDATE users SET custom_elo=? WHERE discord_id=?", (new_elo, uid))

        await db.commit()


# ── 내전 기록 관련 ──

async def create_match(blue_team: list[int], red_team: list[int], recorded_by: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO matches (blue_team, red_team, recorded_by) VALUES (?, ?, ?)",
            (",".join(str(i) for i in blue_team), ",".join(str(i) for i in red_team), recorded_by),
        )
        match_id = cursor.lastrowid

        for uid in blue_team:
            await db.execute(
                "INSERT INTO match_records (match_id, discord_id, team) VALUES (?, ?, 'blue')",
                (match_id, uid),
            )
        for uid in red_team:
            await db.execute(
                "INSERT INTO match_records (match_id, discord_id, team) VALUES (?, ?, 'red')",
                (match_id, uid),
            )

        await db.commit()
        return match_id


async def set_match_winner(match_id: int, winner: str):
    async with aiosqlite.connect(DB_PATH) as db:
        # 이미 결과가 등록된 매치인지 확인
        cursor = await db.execute("SELECT winner, blue_team, red_team FROM matches WHERE match_id=?", (match_id,))
        match = await cursor.fetchone()
        if not match:
            return
        if match[0] is not None:
            return  # 이미 결과 등록됨

        await db.execute("UPDATE matches SET winner=? WHERE match_id=?", (winner, match_id))
        await db.execute(
            "UPDATE match_records SET result=CASE WHEN team=? THEN 'win' ELSE 'lose' END WHERE match_id=?",
            (winner, match_id),
        )
        await db.commit()

    # ELO 업데이트
    blue_ids = [int(x) for x in match[1].split(",")]
    red_ids = [int(x) for x in match[2].split(",")]
    if winner == "blue":
        await update_elo_after_match(blue_ids, red_ids)
    else:
        await update_elo_after_match(red_ids, blue_ids)


async def get_user_record(discord_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT result, COUNT(*) as cnt FROM match_records WHERE discord_id=? AND result IS NOT NULL GROUP BY result",
            (discord_id,),
        )
        rows = await cursor.fetchall()
        record = {"win": 0, "lose": 0}
        for row in rows:
            record[row["result"]] = row["cnt"]
        return record


async def get_recent_matches(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM matches ORDER BY played_at DESC LIMIT ?", (limit,)
        )
        return await cursor.fetchall()
