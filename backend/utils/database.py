from sqlalchemy import create_engine, MetaData, text, event
from sqlalchemy.orm import sessionmaker, declarative_base
from utils.logger import logger
from config import SQLALCHEMY_DATABASE_URI
import os

# Get timezone from environment variable
timezone = os.getenv("DATABASE_TIMEZONE", "UTC")

# Create engine with timezone configuration
engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    connect_args={"options": f"-c timezone={timezone}"}
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


def init_db():
    # Timezone is automatically set for all connections via the event listener
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    db = next(get_db())
    # Create a default user
    from models.User import User

    user = User(
        username="admin",
        role="admin",
    )
    user.set_password("password")
    db.add(user)
    db.commit()
    logger.info("Default user created")


def check_tables_exist():
    db = next(get_db())
    # Check if the users table exists using information_schema
    result = db.execute(
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

    if not result:
        init_db()
    else:
        logger.info("Database tables already exist")
