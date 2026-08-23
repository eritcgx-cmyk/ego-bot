"""
Async SQLAlchemy Engine and Session Factory
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import DATABASE_URL, logger

class Base(DeclarativeBase):
    pass

# Configure connect args depending on dialect
connect_args = {}
if "sqlite" in DATABASE_URL:
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args,
    pool_pre_ping=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def init_db() -> None:
    """Initialize tables in the database and auto-migrate missing columns."""
    # Ensure all database models are imported and registered on Base.metadata
    import database.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Auto-migrate welcome_configs missing columns
        for col_def in [
            "ALTER TABLE welcome_configs ADD COLUMN leave_enabled BOOLEAN DEFAULT 0",
            "ALTER TABLE welcome_configs ADD COLUMN leave_channel_id BIGINT",
            "ALTER TABLE welcome_configs ADD COLUMN leave_title VARCHAR(255)",
            "ALTER TABLE welcome_configs ADD COLUMN leave_message TEXT",
            "ALTER TABLE welcome_configs ADD COLUMN leave_color INTEGER DEFAULT 15680324",
            "ALTER TABLE guild_configs ADD COLUMN video_channel_id BIGINT",
            "ALTER TABLE guild_configs ADD COLUMN bot_manager_role_id BIGINT",
            "ALTER TABLE automod_configs ADD COLUMN block_links BOOLEAN DEFAULT 0",
            "ALTER TABLE automod_configs ADD COLUMN punishment_type VARCHAR(32) DEFAULT 'timeout'",
            "ALTER TABLE automod_configs ADD COLUMN punishment_duration INTEGER DEFAULT 600"
        ]:
            try:
                from sqlalchemy import text
                await conn.execute(text(col_def))
            except Exception:
                pass

    logger.info("Database schema verified and tables created.")

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async session context generator."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
