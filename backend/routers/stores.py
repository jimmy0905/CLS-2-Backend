from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from models.db_config import get_db
from models.Store import Store
from models.District import District
from models.Source import Source
from models.Region import Region
from utils.security import get_current_user
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(
    prefix="/stores",
    tags=["stores"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class DistrictResponse(BaseModel):
    id: int
    name: str


class SourceResponse(BaseModel):
    id: int
    name: str


class RegionResponse(BaseModel):
    id: int
    name: str


class StoreResponse(BaseModel):
    id: int
    name: str
    district: DistrictResponse
    source: SourceResponse
    region: RegionResponse
    is_active: bool


@router.get("/")
async def get_stores(db: Session = Depends(get_db)) -> List[StoreResponse]:
    stores = (
        db.query(Store)
        .options(joinedload(Store.district), joinedload(Store.source))
        .all()
    )
    return stores


@router.get("/{store_id}")
async def get_store(store_id: int, db: Session = Depends(get_db)) -> StoreResponse:
    store = (
        db.query(Store)
        .options(joinedload(Store.district), joinedload(Store.source))
        .filter(Store.id == store_id)
        .first()
    )
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store


class CreateStoreRequest(BaseModel):
    store_id: int
    source_id: int
    name: str
    district_id: Optional[int] = None
    district_name: Optional[str] = None
    source_id: Optional[int] = None
    source_name: Optional[str] = None
    region_id: Optional[int] = None
    region_name: Optional[str] = None


@router.post("/")
async def create_store(
    create_store_request: CreateStoreRequest, db: Session = Depends(get_db)
) -> StoreResponse:
    # Check if district id and district name are provided together
    if (
        create_store_request.district_id is not None
        and create_store_request.district_name is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="District id and district name cannot be provided together",
        )
    # Check if source id and source name are provided together
    if (
        create_store_request.source_id is not None
        and create_store_request.source_name is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="Source id and source name cannot be provided together",
        )
    # Check if at least one of region id or region name is provided
    if (
        create_store_request.region_id is None
        and create_store_request.region_name is None
    ):
        raise HTTPException(
            status_code=400,
            detail="Either region id or region name must be provided",
        )

    # Check if region id and region name are provided together
    if (
        create_store_request.region_id is not None
        and create_store_request.region_name is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="Region id and region name cannot be provided together",
        )

    # If store id is provided, check if store exists
    if create_store_request.store_id:
        store = (
            db.query(Store).filter(Store.id == create_store_request.store_id).first()
        )
        if store:
            raise HTTPException(status_code=400, detail="Store id already exists")
    # If district id is provided, check if district exists
    if create_store_request.district_id:
        district = (
            db.query(District)
            .filter(District.id == create_store_request.district_id)
            .first()
        )
        if not district:
            raise HTTPException(status_code=404, detail="District not found")
    # If district name is provided, check if district exists
    if create_store_request.district_name:
        district = (
            db.query(District)
            .filter(District.name == create_store_request.district_name)
            .first()
        )
        if not district:
            raise HTTPException(status_code=404, detail="District not found")

    if not district:
        raise HTTPException(status_code=404, detail="District not found")

    # If region id is provided, check if region exists
    if create_store_request.region_id:
        region = (
            db.query(Region).filter(Region.id == create_store_request.region_id).first()
        )
        if not region:
            raise HTTPException(status_code=404, detail="Region not found")
    # If region name is provided, check if region exists
    if create_store_request.region_name:
        region = (
            db.query(Region)
            .filter(Region.name == create_store_request.region_name)
            .first()
        )
        if not region:
            raise HTTPException(status_code=404, detail="Region not found")
    # If source id is provided, check if source exists
    if create_store_request.source_id:
        source = (
            db.query(Source).filter(Source.id == create_store_request.source_id).first()
        )
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
    # If source name is provided, check if source exists
    if create_store_request.source_name:
        source = (
            db.query(Source)
            .filter(Source.name == create_store_request.source_name)
            .first()
        )

    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    store = Store(
        id=create_store_request.store_id,
        name=create_store_request.name,
        district_id=district.id,
        source_id=source.id,
        region_id=region.id,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    return StoreResponse(
        id=store.id,
        name=store.name,
        district=DistrictResponse(id=store.district_id, name=store.district.name),
        source=SourceResponse(id=store.source_id, name=store.source.name),
        region=RegionResponse(id=store.region_id, name=store.region.name),
    )


class UpdateStoreRequest(BaseModel):
    name: Optional[str] = None
    district_id: Optional[int] = None
    source_id: Optional[int] = None
    region_id: Optional[int] = None
    is_active: Optional[bool] = None


@router.put("/{store_id}")
async def update_store(
    store_id: int,
    update_store_request: UpdateStoreRequest,
    db: Session = Depends(get_db),
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if update_store_request.name:
        store.name = update_store_request.name
    if update_store_request.district_id:
        district = (
            db.query(District)
            .filter(District.id == update_store_request.district_id)
            .first()
        )
        if not district:
            raise HTTPException(status_code=404, detail="District not found")
        store.district_id = update_store_request.district_id
    if update_store_request.source_id:
        source = (
            db.query(Source).filter(Source.id == update_store_request.source_id).first()
        )
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        store.source_id = update_store_request.source_id
    if update_store_request.region_id:
        region = (
            db.query(Region).filter(Region.id == update_store_request.region_id).first()
        )
        if not region:
            raise HTTPException(status_code=404, detail="Region not found")
        store.region_id = update_store_request.region_id
    if update_store_request.is_active is not None:
        store.is_active = update_store_request.is_active
    db.commit()
    db.refresh(store)
    return store


@router.delete("/{store_id}")
async def delete_store(
    store_id: int,
    db: Session = Depends(get_db),
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.is_active = False
    db.commit()
    return {"message": "Store dseleted successfully"}
