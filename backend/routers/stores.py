from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from utils.database import get_db
from models.Store import Store
from utils.security import get_current_user
from pydantic import BaseModel
from typing import Optional, List, Annotated    
from datetime import datetime
import pandas as pd
import os

router = APIRouter(
    prefix="/stores",
    tags=["stores"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class StoreResponse(BaseModel):
    id: int
    store_name_english: str
    store_name_local: Optional[str] = None
    bu_key: Optional[str] = None
    area_manager: Optional[str] = None
    store_format: Optional[str] = None
    store_type: Optional[str] = None
    operations_controller: Optional[str] = None
    regional_manager: Optional[str] = None
    px: Optional[str] = None
    csr: Optional[str] = None
    dr: Optional[str] = None
    mag_type: Optional[str] = None
    cf_grouping: Optional[str] = None
    store_brand: Optional[str] = None
    competitor: Optional[str] = None
    region: Optional[str] = None
    area: Optional[str] = None
    territory: Optional[str] = None
    toh: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    operations_manager: Optional[str] = None
    district_manager: Optional[str] = None
    sic: Optional[str] = None
    tech_life_type: Optional[str] = None
    operation_manager_tl: Optional[str] = None
    region_manager_tl: Optional[str] = None
    relocation: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    store_open_date: Optional[Date] = None
    store_close_date: Optional[Date] = None
    is_closed: bool


@router.get("/")
async def get_stores(db: Session = Depends(get_db)) -> List[StoreResponse]:
    stores = (
        db.query(Store)
        .options(
        )
        .all()
    )
    return [
        StoreResponse(
            id=store.id,
            store_name_english=store.store_name_english,
            store_name_local=store.store_name_local,
            bu_key=store.bu_key,
            area_manager=store.area_manager,
            store_format=store.store_format,
            store_type=store.store_type,
            operations_controller=store.operations_controller,
            regional_manager=store.regional_manager,
            px=store.px,
            csr=store.csr,
            dr=store.dr,
            mag_type=store.mag_type,
            cf_grouping=store.cf_grouping,
            store_brand=store.store_brand,
            competitor=store.competitor,
            region=store.region,
            area=store.area,
            territory=store.territory,
            toh=store.toh,
            district=store.district,
            city=store.city,
            operations_manager=store.operations_manager,
            district_manager=store.district_manager,
            sic=store.sic,
            tech_life_type=store.tech_life_type,
            operation_manager_tl=store.operation_manager_tl,
            region_manager_tl=store.region_manager_tl,
            relocation=store.relocation,
            latitude=store.latitude,
            longitude=store.longitude,
            store_open_date=store.store_open_date,
            store_close_date=store.store_close_date,
            is_closed=store.is_closed,
        )
        for store in stores
    ]


@router.get("/{store_id}")
async def get_store(store_id: int, db: Session = Depends(get_db)) -> StoreResponse:
    store = (
        db.query(Store)
        .options(
        )
        .filter(Store.id == store_id)
        .first()
    )
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return StoreResponse(
        id=store.id,
        store_name_english=store.store_name_english,
        store_name_local=store.store_name_local,
        bu_key=store.bu_key,
        area_manager=store.area_manager,
        store_format=store.store_format,
        store_type=store.store_type,
        operations_controller=store.operations_controller,
        regional_manager=store.regional_manager,
        px=store.px,
        csr=store.csr,
        dr=store.dr,
        mag_type=store.mag_type,
        cf_grouping=store.cf_grouping,
        store_brand=store.store_brand,
        competitor=store.competitor,
        region=store.region,
        area=store.area,
        territory=store.territory,
        toh=store.toh,
        district=store.district,
        city=store.city,
        operations_manager=store.operations_manager,
        district_manager=store.district_manager,
        sic=store.sic,
        tech_life_type=store.tech_life_type,
        operation_manager_tl=store.operation_manager_tl,
        region_manager_tl=store.region_manager_tl,
        relocation=store.relocation,
        latitude=store.latitude,
        longitude=store.longitude,
        store_open_date=store.store_open_date,
        store_close_date=store.store_close_date,
        is_closed=store.is_closed,
    )


class CreateStoreRequest(BaseModel):
    store_id: int
    store_name_english: str
    store_name_local: Optional[str] = None
    bu_key: Optional[str] = None
    area_manager: Optional[str] = None
    store_format: Optional[str] = None
    store_type: Optional[str] = None
    operations_controller: Optional[str] = None
    regional_manager: Optional[str] = None
    px: Optional[str] = None
    csr: Optional[str] = None
    dr: Optional[str] = None
    mag_type: Optional[str] = None
    cf_grouping: Optional[str] = None
    store_brand: Optional[str] = None
    competitor: Optional[str] = None
    region: Optional[str] = None
    area: Optional[str] = None
    territory: Optional[str] = None
    toh: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    operations_manager: Optional[str] = None
    district_manager: Optional[str] = None
    sic: Optional[str] = None
    tech_life_type: Optional[str] = None
    operation_manager_tl: Optional[str] = None
    region_manager_tl: Optional[str] = None
    relocation: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    store_open_date: Optional[Date] = None
    store_close_date: Optional[Date] = None
    is_closed: bool


@router.post("/")
async def create_store(
    create_store_request: CreateStoreRequest, db: Session = Depends(get_db)
) -> StoreResponse:

    # If store id is provided, check if store exists
    if create_store_request.store_id:
        store = db.query(Store).filter(Store.id == create_store_request.store_id).first()
        if store:
            raise HTTPException(status_code=400, detail="Store id already exists")
    
    store = Store(
        id=create_store_request.store_id,
        store_name_english=create_store_request.store_name_english,
        store_name_local=create_store_request.store_name_local,
        bu_key=create_store_request.bu_key,
        area_manager=create_store_request.area_manager,
        store_format=create_store_request.store_format,
        store_type=create_store_request.store_type,
        operations_controller=create_store_request.operations_controller,
        regional_manager=create_store_request.regional_manager,
        px=create_store_request.px,
        csr=create_store_request.csr,
        dr=create_store_request.dr,
        mag_type=create_store_request.mag_type,
        cf_grouping=create_store_request.cf_grouping,
        store_brand=create_store_request.store_brand,
        competitor=create_store_request.competitor,
        region=create_store_request.region,
        area=create_store_request.area,
        territory=create_store_request.territory,
        toh=create_store_request.toh,
        district=create_store_request.district,
        city=create_store_request.city,
        operations_manager=create_store_request.operations_manager,
        district_manager=create_store_request.district_manager,
        sic=create_store_request.sic,
        tech_life_type=create_store_request.tech_life_type,
        operation_manager_tl=create_store_request.operation_manager_tl,
        region_manager_tl=create_store_request.region_manager_tl,
        relocation=create_store_request.relocation,
        latitude=create_store_request.latitude,
        longitude=create_store_request.longitude,
        store_open_date=create_store_request.store_open_date,
        store_close_date=create_store_request.store_close_date,
        is_closed=create_store_request.is_closed,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    return StoreResponse(
        id=store.id,
        store_name_english=store.store_name_english,
        store_name_local=store.store_name_local,
        bu_key=store.bu_key,
        area_manager=store.area_manager,
        store_format=store.store_format,
        store_type=store.store_type,
        operations_controller=store.operations_controller,
        regional_manager=store.regional_manager,
        px=store.px,
        csr=store.csr,
        dr=store.dr,
        mag_type=store.mag_type,
        cf_grouping=store.cf_grouping,
        store_brand=store.store_brand,
        competitor=store.competitor,
        region=store.region,
        area=store.area,
        territory=store.territory,
        toh=store.toh,
        district=store.district,
        city=store.city,
        operations_manager=store.operations_manager,
        district_manager=store.district_manager,
        sic=store.sic,
        tech_life_type=store.tech_life_type,
        operation_manager_tl=store.operation_manager_tl,
        region_manager_tl=store.region_manager_tl,
        relocation=store.relocation,
        latitude=store.latitude,
        longitude=store.longitude,
        store_open_date=store.store_open_date,
        store_close_date=store.store_close_date,
        is_closed=store.is_closed,
    )


class UpdateStoreRequest(BaseModel):
    store_name_english: Optional[str] = None
    store_name_local: Optional[str] = None
    bu_key: Optional[str] = None
    area_manager: Optional[str] = None
    store_format: Optional[str] = None
    store_type: Optional[str] = None
    operations_controller: Optional[str] = None
    regional_manager: Optional[str] = None
    px: Optional[str] = None
    csr: Optional[str] = None
    dr: Optional[str] = None
    mag_type: Optional[str] = None
    cf_grouping: Optional[str] = None
    store_brand: Optional[str] = None
    competitor: Optional[str] = None
    region: Optional[str] = None
    area: Optional[str] = None
    territory: Optional[str] = None
    toh: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    operations_manager: Optional[str] = None
    district_manager: Optional[str] = None
    sic: Optional[str] = None
    tech_life_type: Optional[str] = None
    operation_manager_tl: Optional[str] = None
    region_manager_tl: Optional[str] = None
    relocation: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    store_open_date: Optional[Date] = None
    store_close_date: Optional[Date] = None
    is_closed: Optional[bool] = None


@router.put("/{store_id}")
async def update_store(
    store_id: int,
    update_store_request: UpdateStoreRequest,
    db: Session = Depends(get_db),
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    if update_store_request.store_name_english:
        store.store_name_english = update_store_request.store_name_english
    if update_store_request.store_name_local:
        store.store_name_local = update_store_request.store_name_local
    if update_store_request.bu_key:
        store.bu_key = update_store_request.bu_key
    if update_store_request.area_manager:
        store.area_manager = update_store_request.area_manager
    if update_store_request.store_format:
        store.store_format = update_store_request.store_format
    if update_store_request.store_type:
        store.store_type = update_store_request.store_type
    if update_store_request.operations_controller:
        store.operations_controller = update_store_request.operations_controller
    if update_store_request.regional_manager:
        store.regional_manager = update_store_request.regional_manager
    if update_store_request.px:
        store.px = update_store_request.px
    if update_store_request.csr:
        store.csr = update_store_request.csr
    if update_store_request.dr:
        store.dr = update_store_request.dr
    if update_store_request.mag_type:
        store.mag_type = update_store_request.mag_type
    if update_store_request.cf_grouping:
        store.cf_grouping = update_store_request.cf_grouping
    if update_store_request.store_brand:
        store.store_brand = update_store_request.store_brand
    if update_store_request.competitor:
        store.competitor = update_store_request.competitor
    if update_store_request.region:
        store.region = update_store_request.region
    if update_store_request.area:
        store.area = update_store_request.area
    if update_store_request.territory:
        store.territory = update_store_request.territory
    if update_store_request.toh:
        store.toh = update_store_request.toh
    if update_store_request.district:
        store.district = update_store_request.district
    if update_store_request.city:
        store.city = update_store_request.city
    if update_store_request.operations_manager:
        store.operations_manager = update_store_request.operations_manager
    if update_store_request.district_manager:
        store.district_manager = update_store_request.district_manager
    if update_store_request.sic:
        store.sic = update_store_request.sic
    if update_store_request.tech_life_type:
        store.tech_life_type = update_store_request.tech_life_type
    if update_store_request.operation_manager_tl:
        store.operation_manager_tl = update_store_request.operation_manager_tl
    if update_store_request.region_manager_tl:
        store.region_manager_tl = update_store_request.region_manager_tl
    if update_store_request.relocation:
        store.relocation = update_store_request.relocation
    if update_store_request.latitude:
        store.latitude = update_store_request.latitude
    if update_store_request.longitude:
        store.longitude = update_store_request.longitude
    if update_store_request.store_open_date:
        store.store_open_date = update_store_request.store_open_date
    if update_store_request.store_close_date:
        store.store_close_date = update_store_request.store_close_date
    if update_store_request.is_closed is not None:
        store.is_closed = update_store_request.is_closed
    
    db.commit()
    db.refresh(store)
    return StoreResponse(
        id=store.id,
        store_name_english=store.store_name_english,
        store_name_local=store.store_name_local,
        bu_key=store.bu_key,
        area_manager=store.area_manager,
        store_format=store.store_format,
        store_type=store.store_type,
        operations_controller=store.operations_controller,
        regional_manager=store.regional_manager,
        px=store.px,
        csr=store.csr,
        dr=store.dr,
        mag_type=store.mag_type,
        cf_grouping=store.cf_grouping,
        store_brand=store.store_brand,
        competitor=store.competitor,
        region=store.region,
        area=store.area,
        territory=store.territory,
        toh=store.toh,
        district=store.district,
        city=store.city,
        operations_manager=store.operations_manager,
        district_manager=store.district_manager,
        sic=store.sic,
        tech_life_type=store.tech_life_type,
        operation_manager_tl=store.operation_manager_tl,
        region_manager_tl=store.region_manager_tl,
        relocation=store.relocation,
        latitude=store.latitude,
        longitude=store.longitude,
        store_open_date=store.store_open_date,
        store_close_date=store.store_close_date,
        is_closed=store.is_closed,
    )


@router.delete("/{store_id}")
async def delete_store(
    store_id: int,
    db: Session = Depends(get_db),
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.is_closed = False
    db.commit()
    return {"message": "Store dseleted successfully"}

@router.post("/upsert_stores_from_csv")
async def upsert_stores_from_csv(
    file: Annotated[UploadFile, File()],
    db: Session = Depends(get_db),
):
    # Check if the file is a CSV file
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="File must be a CSV file")
    
    tmp_file_path = None
    try:
        # Create a tmp file name with the current timestamp
        tmp_file_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        tmp_file_path = os.path.join("/tmp", tmp_file_name)
        # Write the file to the tmp file
        with open(tmp_file_path, "wb") as f:
            contents = file.file.read()
            f.write(contents)
        # Read the file into a pandas dataframe
        df = pd.read_csv(tmp_file_path, encoding="utf-8", sep=",", encoding_errors="ignore", on_bad_lines="warn", engine="python", quotechar='"', escapechar="\\")
        # Iterate over the dataframe and upsert the stores
        for index, row in df.iterrows():
            store = Store(
                id=row["store_id"],
                store_name_english=row["store_name_english"],
                store_name_local=row["store_name_local"],
                bu_key=row["bu_key"],
                area_manager=row["area_manager"],
                store_format=row["store_format"],
                store_type=row["store_type"],
                operations_controller=row["operations_controller"],
                regional_manager=row["regional_manager"],
                px=row["px"],
                csr=row["csr"],
                dr=row["dr"],
                mag_type=row["mag_type"],
                cf_grouping=row["cf_grouping"],
                store_brand=row["store_brand"],
                competitor=row["competitor"],
                region=row["region"],
                area=row["area"],
                territory=row["territory"],
                toh=row["toh"],
                district=row["district"],
                city=row["city"],
                operations_manager=row["operations_manager"],
                district_manager=row["district_manager"],
                sic=row["sic"],
                tech_life_type=row["tech_life_type"],
                operation_manager_tl=row["operation_manager_tl"],
                region_manager_tl=row["region_manager_tl"],
                relocation=row["relocation"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                store_open_date=row["store_open_date"],
                store_close_date=row["store_close_date"],
                is_closed=row["is_closed"],
            )
            db.merge(store)
        
        db.commit()
        return {"message": "Stores upserted successfully"}
    except Exception as e:
        db.rollback()
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
        raise HTTPException(status_code=400, detail=f"Invalid CSV file: {str(e)}")
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)