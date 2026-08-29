import asyncio
import os
import threading
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import PATH_TO_UPLOAD_FOLDER
from core.logging import logger
from core.time import utc_isoformat, utc_now
from features.identity.service.security import get_current_user
from features.ingestion.service import process_upload_task
from infrastructure.database.dbo.UploadTask import UploadTask
from infrastructure.database.session import SessionLocal, get_db

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
    
    def save_and_validate_file():
        # Rename the file with the current timestamp
        file_name = f"{utc_now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        file_path = os.path.join(PATH_TO_UPLOAD_FOLDER, file_name)

        # Write the file
        with open(file_path, "wb") as f:
            contents = file.file.read()
            f.write(contents)

        # Validate the saved file
        df = pd.read_csv(
            file_path,
            encoding="utf-8",
            sep=",",
            encoding_errors="ignore",
            on_bad_lines="warn",
            engine="python",
            quotechar='"',
            escapechar="\\",
        )

        logger.info(f"Successfully parsed CSV file with {len(df)} rows")
        return file_name, file_path, len(df)
    
    # Save the file first
    try:
        file_name, file_path, row_count = await asyncio.to_thread(save_and_validate_file)
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="CSV file is empty")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV file: {str(e)}")

    # File has been validated and saved successfully

    # Create a new upload task
    upload_task = UploadTask(
        file_name=file_name,
        file_path=file_name,
        status="pending",
        total_rows=row_count,
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

    return build_upload_task_response(upload_task)



class UploadTaskResponse(BaseModel):
    id: str
    file_name: str
    file_path: str
    status: str
    total_rows: int
    processed_rows: int
    created_at: str
    updated_at: str
    error_count: int


def build_upload_task_response(upload_task: UploadTask) -> UploadTaskResponse:
    return UploadTaskResponse(
        id=upload_task.id,
        file_name=upload_task.file_name,
        file_path=upload_task.file_path,
        status=upload_task.status,
        total_rows=upload_task.total_rows,
        processed_rows=upload_task.processed_rows,
        created_at=utc_isoformat(upload_task.created_at) or "",
        updated_at=utc_isoformat(upload_task.updated_at) or "",
        error_count=len(upload_task.errors),
    )


@router.get("/upload_tasks/{upload_task_id}")
async def get_upload_task(
    upload_task_id: str, db: Session = Depends(get_db)
) -> UploadTaskResponse:
    upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
    if not upload_task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return build_upload_task_response(upload_task)


@router.get("")
async def get_upload_tasks(db: Session = Depends(get_db)) -> list[UploadTaskResponse]:
    upload_tasks = db.query(UploadTask).order_by(UploadTask.created_at.desc()).all()
    return [build_upload_task_response(upload_task) for upload_task in upload_tasks]


@router.get("/download/example")
async def download_example_task(db: Session = Depends(get_db)):
    return FileResponse(os.path.join(PATH_TO_UPLOAD_FOLDER, "example.csv"))


@router.get("/download/{upload_task_id}")
async def download_uploaded_task(upload_task_id: str, db: Session = Depends(get_db)):
    upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
    if not upload_task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return FileResponse(os.path.join(PATH_TO_UPLOAD_FOLDER, upload_task.file_path))
