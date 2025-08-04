from typing import Annotated
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from utils.backgrounTaskHandler import process_upload_task
from config import PATH_TO_UPLOAD_FOLDER
from models.db_config import get_db
from sqlalchemy.orm import Session
import pandas as pd
from models.UploadTask import UploadTask
import os
from datetime import datetime
import asyncio
from pydantic import BaseModel
from fastapi.responses import FileResponse
from utils.security import get_current_user

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


@router.post("/upload_tasks")
async def upload_tasks(
    file: Annotated[UploadFile, File()],
    db: Session = Depends(get_db),
):
    # Check if the file is a Excel file
    if (
        file.content_type
        != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ):
        raise HTTPException(status_code=400, detail="File must be an Excel file")
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
        df = pd.read_excel(file_path)
        # Check if the file has the required columns (store_id, comment, reported_at)
        required_columns = ["store_id", "comment", "reported_at"]
        if not all(col in df.columns for col in required_columns):
            os.remove(file_path)  # Clean up invalid file
            raise HTTPException(
                status_code=400, detail="File must have the required columns"
            )

        # Check if the file is empty
        if df.empty:
            os.remove(file_path)  # Clean up empty file
            raise HTTPException(status_code=400, detail="File is empty")

    except Exception as e:
        # Clean up if file was created
        if "file_path" in locals() and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {str(e)}")

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
    asyncio.create_task(process_upload_task(file_path, db, upload_task.id))
    return upload_task


class UploadTaskError(BaseModel):
    id: str
    upload_task_id: str
    error_message: str
    input_store_id: int
    input_comment: str
    input_reported_at: str
    created_at: datetime
    updated_at: datetime


class UploadTaskResponse(BaseModel):
    id: str
    file_name: str
    file_path: str
    status: str
    total_rows: int
    processed_rows: int
    created_at: datetime
    updated_at: datetime
    errors: list[UploadTaskError]


@router.get("/upload_tasks/{upload_task_id}")
async def get_upload_task(
    upload_task_id: int, db: Session = Depends(get_db)
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
        errors=[error.to_dict() for error in upload_task.errors],
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
            errors=[error.to_dict() for error in upload_task.errors],
        )
        for upload_task in upload_tasks
    ]


@router.get("/download/example")
async def download_example_task(db: Session = Depends(get_db)):
    return FileResponse(os.path.join(PATH_TO_UPLOAD_FOLDER, "example.xlsx"))


@router.get("/download/{upload_task_id}")
async def download_uploaded_task(upload_task_id: str, db: Session = Depends(get_db)):
    upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
    if not upload_task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return FileResponse( os.path.join(PATH_TO_UPLOAD_FOLDER, upload_task.file_path))
