import os
import dotenv

dotenv.load_dotenv()

PATH_TO_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "upload_tasks")
