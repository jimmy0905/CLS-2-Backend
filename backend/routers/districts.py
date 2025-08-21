from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.database import get_db
from models.District import District
from utils.security import get_current_user
from pydantic import BaseModel
from typing import List

router = APIRouter(
    prefix="/districts",
    tags=["districts"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)

class DistrictResponse(BaseModel):
    id: int
    name: str


@router.get("/")
async def get_districts(db: Session = Depends(get_db)) -> List[DistrictResponse]:
    districts = db.query(District).all()
    return districts


@router.get("/{district_id}")
async def get_district(district_id: int, db: Session = Depends(get_db)) -> DistrictResponse:
    district = db.query(District).filter(District.id == district_id).first()
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    return district


class CreateDistrictRequest(BaseModel):
    name: str


@router.post("/")
async def create_district(
    create_district_request: CreateDistrictRequest, db: Session = Depends(get_db)
):
    # Check if district already exists
    district = (
        db.query(District).filter(District.name == create_district_request.name).first()
    )
    if district:
        raise HTTPException(status_code=400, detail="District already exists")
    district = District(name=create_district_request.name)
    db.add(district)
    db.commit()
    db.refresh(district)
    return district


class UpdateDistrictRequest(BaseModel):
    name: str


@router.put("/{district_id}")
async def update_district(
    district_id: int,
    update_district_request: UpdateDistrictRequest,
    db: Session = Depends(get_db),
):
    # Check if district exists
    district = db.query(District).filter(District.id == district_id).first()
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    district.name = update_district_request.name
    db.commit()
    db.refresh(district)
    return district


@router.delete("/{district_id}")
async def delete_district(district_id: int, db: Session = Depends(get_db)):
    district = db.query(District).filter(District.id == district_id).first()
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    db.delete(district)
    db.commit()
    return {"message": "District deleted successfully"}
