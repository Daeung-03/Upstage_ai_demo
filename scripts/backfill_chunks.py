import asyncio
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models import enums
from app.models.user import User
from app.models.term import Term, TermVersion, TermChunk, TermClause
from app.models.calendar import CalendarEvent, Notification
from app.models.chat import ChatSession, ChatMessage
from app.models.dispute import DisputeCase
from app.services import term_service, ai_client

async def backfill():
    async with AsyncSessionLocal() as db:
        # Find versions that are latest but have 0 chunks or dummy chunks
        q = select(TermVersion).where(TermVersion.is_latest == True)
        versions = (await db.execute(q)).scalars().all()
        
        for v in versions:
            chunks = (await db.execute(select(TermChunk).where(TermChunk.version_id == v.id))).scalars().all()
            needs_backfill = False
            
            if len(chunks) == 0:
                needs_backfill = True
            elif chunks and chunks[0].content.startswith("# 서비스 이용약관"):
                needs_backfill = True
                
            if needs_backfill:
                print(f"Backfilling chunks for TermVersion {v.id}...")
                # Delete existing dummy chunks
                for c in chunks:
                    await db.delete(c)
                
                if not v.raw_text:
                    print("Skipping, no raw_text.")
                    continue
                    
                new_chunks = term_service._split_chunks(v.raw_text)
                vectors = await ai_client.embed_chunks(new_chunks)
                
                for idx, (content, vector) in enumerate(zip(new_chunks, vectors)):
                    db.add(TermChunk(
                        term_id=v.term_id,
                        version_id=v.id,
                        chunk_index=idx,
                        content=content,
                        embedding=vector,
                    ))
                print(f"Added {len(new_chunks)} chunks.")
                
        await db.commit()
        print("Chunk backfill complete.")

if __name__ == "__main__":
    asyncio.run(backfill())
