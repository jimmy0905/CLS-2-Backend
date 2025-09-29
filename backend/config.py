import os
import dotenv

dotenv.load_dotenv()

PATH_TO_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "upload_tasks")

DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = os.getenv("DATABASE_PORT")
DATABASE_NAME = os.getenv("DATABASE_NAME")

SQLALCHEMY_DATABASE_URI = f"postgresql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"

# Multi-threading configuration for survey processing
MAX_WORKER_THREADS = int(os.getenv("MAX_WORKER_THREADS", "3"))  # Default to 4 threads
