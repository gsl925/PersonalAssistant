import asyncio
from backend.knowledge.db import init_db, async_engine
from backend.knowledge.models import Base

async def main():
    print("Initializing database tables...")
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database initialized successfully!")

    # Also insert default project
    from backend.knowledge.db import async_session_maker
    from backend.knowledge.models import Project
    import uuid
    async with async_session_maker() as session:
        default_project = Project(
            id=uuid.uuid4(),
            name="General",
            description="Default project for uncategorized content"
        )
        session.add(default_project)
        await session.commit()
    print("Default project created.")

if __name__ == "__main__":
    asyncio.run(main())
