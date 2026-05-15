import asyncio
from sqlalchemy import text
from app.database import engine

async def migrate():
    async with engine.begin() as conn:
        with open("migrations/0004_termclause_dispute_user_action.sql") as f:
            await conn.execute(text(f.read()))
    print("Migration 0004 applied.")

if __name__ == "__main__":
    asyncio.run(migrate())
