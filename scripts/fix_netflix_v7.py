import asyncio
from sqlalchemy import select, func, update, delete
from app.database import AsyncSessionLocal
from app.models import enums
from app.models.user import User
from app.models.term import Term, TermVersion, TermChunk, TermClause
from app.models.calendar import CalendarEvent, Notification
from app.models.chat import ChatSession, ChatMessage
from app.models.dispute import DisputeCase

async def fix_versions():
    async with AsyncSessionLocal() as db:
        # Find latest term versions with 0 clauses
        q = select(TermVersion).where(TermVersion.is_latest == True)
        versions = (await db.execute(q)).scalars().all()
        for v in versions:
            clause_count = (await db.execute(select(func.count(TermClause.id)).where(TermClause.version_id == v.id))).scalar()
            if clause_count == 0:
                print(f"TermVersion {v.id} (version {v.version}) has 0 clauses. Fixing...")
                
                # Find previous version
                prev_v = (await db.execute(
                    select(TermVersion)
                    .where(TermVersion.term_id == v.term_id, TermVersion.version < v.version)
                    .order_by(TermVersion.version.desc())
                    .limit(1)
                )).scalar_one_or_none()
                
                # Delete related notifications first to avoid FK constraint error
                await db.execute(delete(Notification).where(Notification.version_id == v.id))
                
                # Delete empty version (this cascades to clauses/chunks if any)
                await db.execute(delete(TermVersion).where(TermVersion.id == v.id))
                
                # Promote previous version
                if prev_v:
                    prev_v.is_latest = True
                    db.add(prev_v)
                    print(f"Promoted version {prev_v.version} to latest.")
                
        await db.commit()
        print("Done fixing Netflix v7 bug.")

if __name__ == "__main__":
    asyncio.run(fix_versions())
