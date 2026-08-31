from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import SQLALCHEMY_DATABASE_URI
from core.logging import logger
from infrastructure.database.base import Base

engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=20,
    pool_timeout=60,
    pool_recycle=1800,
    pool_use_lifo=True,
    connect_args={"options": "-c timezone=UTC"},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def application_tables_exist() -> bool:
    db = SessionLocal()
    try:
        return bool(
            db.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 
                        FROM information_schema.tables 
                        WHERE table_name = 'surveys'
                    )
                    """
                )
            ).scalar()
        )
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")


def check_tables_exist() -> None:
    from core.config import DATABASE_BOOTSTRAP_SCHEMA

    if not application_tables_exist():
        if not DATABASE_BOOTSTRAP_SCHEMA:
            raise RuntimeError(
                "Database tables are missing. Run Alembic migrations or set "
                "DATABASE_BOOTSTRAP_SCHEMA=true for local schema bootstrap."
            )
        init_db()
    else:
        logger.info("Database tables already exist")
