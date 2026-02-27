from typing import Annotated
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from utils.backgrounTaskHandler import process_upload_task
from config import PATH_TO_UPLOAD_FOLDER
from utils.database import get_db, SessionLocal
from sqlalchemy.orm import Session
import pandas as pd
from models.UploadTask import UploadTask
import os
from datetime import datetime
from pydantic import BaseModel
from fastapi.responses import FileResponse
from utils.security import get_current_user
from utils.logger import logger
import threading
import asyncio

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


def background_process_upload_task(file_path: str, upload_task_id: str):
    """
    Background task wrapper that runs in a separate thread.
    This ensures the background task doesn't block the API response.
    """

    async def async_process():
        db = SessionLocal()
        try:
            logger.info(f"Background task started for upload_task_id {upload_task_id}")
            # Update status to "processing" when background task starts
            upload_task = (
                db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
            )
            if upload_task:
                upload_task.status = "processing"
                db.commit()

            # Process the upload task with multi-threading
            await process_upload_task(file_path, db, upload_task_id)

        except Exception as e:
            # Log error and update task status
            logger.error(
                f"Background task failed for upload_task_id {upload_task_id}: {e}"
            )

            # Update task status to failed
            upload_task = (
                db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
            )
            if upload_task:
                upload_task.status = "failed"
                db.commit()
        finally:
            logger.info(
                f"Background task completed for upload_task_id {upload_task_id}"
            )
            db.close()

    # Run the async function in its own event loop in a separate thread
    def run_in_thread():
        try:
            asyncio.run(async_process())
        except Exception as e:
            logger.error(
                f"Thread execution failed for upload_task_id {upload_task_id}: {e}"
            )

    # Start the processing in a daemon thread
    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()


@router.post("/upload_tasks")
async def upload_tasks(
    file: Annotated[UploadFile, File()],
    db: Session = Depends(get_db),
):
    # Check if the file is a CSV file
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="File must be a CSV file")
    # Save the file first
    try:

        # Rename the file with the current timestamp
        file_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        file_path = os.path.join(PATH_TO_UPLOAD_FOLDER, file_name)

        # Write the file
        with open(file_path, "wb") as f:
            contents = file.file.read()
            f.write(contents)

        # Validate the saved file
        try:
            # First, try to read with error reporting to see which lines are problematic
            df = pd.read_csv(
                file_path,
                encoding="utf-8",
                sep=",",
                encoding_errors="ignore",
                on_bad_lines="warn",  # Warn about bad lines but continue
                engine="python",  # Use Python engine for more flexible parsing
                quotechar='"',
                escapechar="\\",
            )

            # Log any warnings about skipped lines
            logger.info(f"Successfully parsed CSV file with {len(df)} rows")

        except pd.errors.EmptyDataError:
            os.remove(file_path)
            raise HTTPException(status_code=400, detail="CSV file is empty")
        except Exception as e:
            os.remove(file_path)
            raise HTTPException(status_code=400, detail=f"Invalid CSV file: {str(e)}")

    except Exception as e:
        # Clean up if file was created
        if "file_path" in locals() and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail=f"Invalid CSV file: {str(e)}")

    # File has been validated and saved successfully

    # Create a new upload task
    upload_task = UploadTask(
        file_name=file_name,
        file_path=file_name,
        status="pending",
        total_rows=len(df),
        processed_rows=0,
    )
    db.add(upload_task)
    db.commit()
    db.refresh(upload_task)

    # Create a background task to process the upload task
    # This will run independently in a separate thread and not block the API response
    logger.info(f"Starting background thread for upload_task_id {upload_task.id}")
    background_process_upload_task(file_path, upload_task.id)
    logger.info(f"Background thread started for upload_task_id {upload_task.id}")

    return upload_task



class UploadTaskResponse(BaseModel):
    id: str
    file_name: str
    file_path: str
    status: str
    total_rows: int
    processed_rows: int
    created_at: datetime
    updated_at: datetime
    error_count: int


@router.get("/upload_tasks/{upload_task_id}")
async def get_upload_task(
    upload_task_id: str, db: Session = Depends(get_db)
) -> UploadTaskResponse:
    upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
    if not upload_task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return UploadTaskResponse(
        id=upload_task.id,
        file_name=upload_task.file_name,
        file_path=upload_task.file_path,
        status=upload_task.status,
        total_rows=upload_task.total_rows,
        processed_rows=upload_task.processed_rows,
        created_at=upload_task.created_at,
        updated_at=upload_task.updated_at,
        error_count=len(upload_task.errors),
    )


@router.get("")
async def get_upload_tasks(db: Session = Depends(get_db)) -> list[UploadTaskResponse]:
    upload_tasks = db.query(UploadTask).order_by(UploadTask.created_at.desc()).all()
    return [
        UploadTaskResponse(
            id=upload_task.id,
            file_name=upload_task.file_name,
            file_path=upload_task.file_path,
            status=upload_task.status,
            total_rows=upload_task.total_rows,
            processed_rows=upload_task.processed_rows,
            created_at=upload_task.created_at,
            updated_at=upload_task.updated_at,
            error_count=len(upload_task.errors),
        )
        for upload_task in upload_tasks
    ]


@router.get("/download/example")
async def download_example_task(db: Session = Depends(get_db)):
    return FileResponse(os.path.join(PATH_TO_UPLOAD_FOLDER, "example.csv"))


@router.get("/download/{upload_task_id}")
async def download_uploaded_task(upload_task_id: str, db: Session = Depends(get_db)):
    upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
    if not upload_task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return FileResponse(os.path.join(PATH_TO_UPLOAD_FOLDER, upload_task.file_path))
