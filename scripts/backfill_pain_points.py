import asyncio
from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models import enums
from app.models.user import User
from app.models.term import Term, TermVersion, TermChunk, TermClause
from app.models.calendar import CalendarEvent, Notification
from app.models.chat import ChatSession, ChatMessage
from app.models.dispute import DisputeCase

async def backfill():
    async with AsyncSessionLocal() as db:
        print("Backfilling NULL risk_level and pain_point_id...")
        await db.execute(
            update(TermClause)
            .where(TermClause.risk_level.is_(None))
            .values(risk_level="medium")
        )
        await db.execute(
            update(TermClause)
            .where(TermClause.pain_point_id.is_(None))
            .values(pain_point_id="ETC-01")
        )
        await db.commit()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(backfill())
