from sqlalchemy import text
from models.db_config import Base, engine, get_db
from models.User import User
from utils.logger import logger


def init_db():
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    db = next(get_db())
    # Create a default user
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
