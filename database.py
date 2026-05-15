from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os

load_dotenv()

raw_database_url = os.getenv("DATABASE_URL", "").strip()
if not raw_database_url:
    raise RuntimeError("DATABASE_URL is not set")

DATABASE_URL = raw_database_url.replace(
    "postgresql://", "postgresql+asyncpg://", 1
).replace(
    "postgres://", "postgresql+asyncpg://", 1
)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=2,
    echo=False,
    connect_args={"ssl": "require"}  # ← add this
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

SessionLocal = AsyncSessionLocal  # alias

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
