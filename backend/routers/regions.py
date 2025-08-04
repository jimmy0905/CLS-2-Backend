from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models.db_config import get_db
from models.Region import Region
from utils.security import get_current_user
from pydantic import BaseModel
from typing import List

router = APIRouter(
    prefix="/regions",
    tags=["regions"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class RegionResponse(BaseModel):
    id: int
    name: str


@router.get("/")
async def get_regions(db: Session = Depends(get_db)) -> List[RegionResponse]:
    regions = db.query(Region).all()
    return regions


@router.get("/{region_id}")
async def get_region(region_id: int, db: Session = Depends(get_db)) -> RegionResponse:
    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    return region


class CreateRegionRequest(BaseModel):
    name: str


@router.post("/")
async def create_region(
    create_region_request: CreateRegionRequest, db: Session = Depends(get_db)
):
    # Check if region already exists
    region = db.query(Region).filter(Region.name == create_region_request.name).first()
    if region:
        raise HTTPException(status_code=400, detail="Region already exists")
    region = Region(name=create_region_request.name)
    db.add(region)
    db.commit()
    db.refresh(region)
    return region


class UpdateRegionRequest(BaseModel):
    name: str


@router.put("/{region_id}")
async def update_region(
    region_id: int,
    update_region_request: UpdateRegionRequest,
    db: Session = Depends(get_db),
):
    # Check if region exists
    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    region.name = update_region_request.name
    db.commit()
    db.refresh(region)
    return region


@router.delete("/{region_id}")
async def delete_region(region_id: int, db: Session = Depends(get_db)):
    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    db.delete(region)
    db.commit()
    return {"message": "Region deleted successfully"}
