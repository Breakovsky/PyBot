from sqlalchemy import Column, Integer, String, BigInteger, Enum, TIMESTAMP, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import enum
import os

Base = declarative_base()

class UserRole(enum.Enum):
    CREATOR = "CREATOR"
    CTO = "CTO"
    IT_HEAD = "IT_HEAD"
    SENIOR_ADMIN = "SENIOR_ADMIN"
    ADMIN = "ADMIN"
    JUNIOR_ADMIN = "JUNIOR_ADMIN"
    USER = "USER"

    # Helper to check hierarchy (lower index = higher privilege)
    def __ge__(self, other):
        if self.__class__ is other.__class__:
            order = list(self.__class__)
            return order.index(self) <= order.index(other)
        return NotImplemented

class TelegramUser(Base):
    __tablename__ = 'telegram_users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String)
    role = Column(Enum(UserRole, name="user_role"), default=UserRole.USER)
    karma_points = Column(Integer, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class TelegramTopic(Base):
    __tablename__ = 'telegram_topics'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    thread_id = Column(Integer, nullable=False)
    description = Column(String)

class Employee(Base):
    __tablename__ = 'employees'
    
    id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=False)
    department = Column(String)
    phone = Column(String)
    workstation = Column(String)
    ad_login = Column(String)
    email = Column(String)
    notes = Column(String)
    is_active = Column(Integer, default=1)  # SQLite uses integers for booleans
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

# DB Setup
POSTGRES_USER = os.getenv("POSTGRES_USER", "netadmin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "netadmin_secret")
POSTGRES_DB = os.getenv("POSTGRES_DB", "netadmin_db")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")

# Use asyncpg driver
DATABASE_URL = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DB}"

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_db():
    async with async_session() as session:
        yield session

