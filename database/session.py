import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import database_url


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    return database_url


engine = create_async_engine(database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_db_session():
    async with AsyncSessionLocal() as session:
        try:
            logger.info("get session")
            yield session
        except Exception:
            logger.exception("Err save to db")
            await session.rollback()
            raise
