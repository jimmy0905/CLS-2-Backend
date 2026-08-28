from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.orm import sessionmaker, declarative_base
from utils.logger import logger
from config import SQLALCHEMY_DATABASE_URI

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
metadata = MetaData()
Base = declarative_base(metadata=metadata)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_default_user() -> None:
    from config import (
        BOOTSTRAP_DEFAULT_ADMIN,
        BOOTSTRAP_DEFAULT_ADMIN_PASSWORD,
        BOOTSTRAP_DEFAULT_ADMIN_USERNAME,
    )
    from models.User import User

    if not BOOTSTRAP_DEFAULT_ADMIN:
        logger.info("Default admin bootstrap is disabled")
        return

    if not BOOTSTRAP_DEFAULT_ADMIN_PASSWORD or not BOOTSTRAP_DEFAULT_ADMIN_PASSWORD.strip():
        raise ValueError(
            "BOOTSTRAP_DEFAULT_ADMIN_PASSWORD is required when "
            "BOOTSTRAP_DEFAULT_ADMIN is enabled"
        )

    db = SessionLocal()
    try:
        existing_user = (
            db.query(User)
            .filter(User.username == BOOTSTRAP_DEFAULT_ADMIN_USERNAME)
            .first()
        )
        if existing_user:
            logger.info("Default user already exists")
            return

        user = User(
            username=BOOTSTRAP_DEFAULT_ADMIN_USERNAME,
            role="admin",
        )
        user.set_password(BOOTSTRAP_DEFAULT_ADMIN_PASSWORD)
        db.add(user)
        db.commit()
        logger.info("Default user created")
    except Exception as error:
        db.rollback()
        logger.error(f"Failed to ensure default user: {error}")
        raise
    finally:
        db.close()


def users_table_exists() -> bool:
    db = SessionLocal()
    try:
        return bool(
            db.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 
                        FROM information_schema.tables 
                        WHERE table_name = 'users'
                    )
                    """
                )
            ).scalar()
        )
    finally:
        db.close()


def usable_user_exists() -> bool:
    """Return whether analytics records can reference a non-deleted user."""

    db = SessionLocal()
    try:
        return bool(
            db.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM users
                        WHERE COALESCE(is_deleted, false) = false
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
    ensure_default_user()


def check_tables_exist() -> None:
    from config import DATABASE_BOOTSTRAP_SCHEMA

    if not users_table_exists():
        if not DATABASE_BOOTSTRAP_SCHEMA:
            raise RuntimeError(
                "Database tables are missing. Run Alembic migrations or set "
                "DATABASE_BOOTSTRAP_SCHEMA=true for local schema bootstrap."
            )
        init_db()
    else:
        logger.info("Database tables already exist")
