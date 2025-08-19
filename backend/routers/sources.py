from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from utils.database import get_db
from models.Source import Source
from utils.security import get_current_user
from pydantic import BaseModel
from typing import List

router = APIRouter(
    prefix="/sources",
    tags=["sources"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class SourceResponse(BaseModel):
    id: int
    name: str


@router.get("/")
async def get_sources(db: Session = Depends(get_db)) -> List[SourceResponse]:
    sources = db.query(Source).all()
    return sources


@router.get("/{source_id}")
async def get_source(source_id: int, db: Session = Depends(get_db)) -> SourceResponse:
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


class CreateSourceRequest(BaseModel):
    name: str


@router.post("/")
async def create_source(
    create_source_request: CreateSourceRequest, db: Session = Depends(get_db)
):
    # Check if source already exists
    source = db.query(Source).filter(Source.name == create_source_request.name).first()
    if source:
        raise HTTPException(status_code=400, detail="Source already exists")
    source = Source(name=create_source_request.name)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


class UpdateSourceRequest(BaseModel):
    name: str


@router.put("/{source_id}")
async def update_source(
    source_id: int,
    update_source_request: UpdateSourceRequest,
    db: Session = Depends(get_db),
):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.name = update_source_request.name
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}")
async def delete_source(source_id: int, db: Session = Depends(get_db)):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete(source)
    db.commit()
    return {"message": "Source deleted successfully"}
