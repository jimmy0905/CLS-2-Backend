from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from utils.database import get_db
from models.Store import Store
from utils.security import get_current_user
from pydantic import BaseModel
from typing import Optional, List, Annotated    
from datetime import datetime, date
import pandas as pd
import numpy as np
import os

router = APIRouter(
    prefix="/stores",
    tags=["stores"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class StoreResponse(BaseModel):
    store_key: int
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
    store_open_date: Optional[date] = None
    store_close_date: Optional[date] = None
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
            store_key=store.store_key,
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


@router.get("/{store_key}")
async def get_store(store_key: int, db: Session = Depends(get_db)) -> StoreResponse:
    store = (
        db.query(Store)
        .options(
        )
        .filter(Store.store_key == store_key)
        .first()
    )
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return StoreResponse(
        store_key=store.store_key,
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
    store_key: int
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
    store_open_date: Optional[date] = None
    store_close_date: Optional[date] = None
    is_closed: bool


@router.post("/")
async def create_store(
    create_store_request: CreateStoreRequest, db: Session = Depends(get_db)
) -> StoreResponse:

    # If store id is provided, check if store exists
    if create_store_request.store_key:
        store = db.query(Store).filter(Store.store_key == create_store_request.store_key).first()
        if store:
            raise HTTPException(status_code=400, detail="Store id already exists")
    
    store = Store(
        store_key=create_store_request.store_key,
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
        store_key=store.store_key,
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

@router.delete("/{store_key}")
async def delete_store(
    store_key: int,
    db: Session = Depends(get_db),
):
    store = db.query(Store).filter(Store.store_key == store_key).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.is_closed = True
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
        df = pd.read_csv(tmp_file_path, encoding="utf-8", sep=",", encoding_errors="ignore", on_bad_lines="warn", engine="python", quotechar='"', escapechar="\\", na_values=[''])
        # Replace all NaN values with None for proper NULL insertion in database
        df = df.replace({np.nan: None})
        # Iterate over the dataframe and upsert the stores
        for index, row in df.iterrows():
            store = Store(
                store_key=row["store_key"],
                store_name_english=row["store_name_english"] if row["store_name_english"] is not None else "N/A",
                store_name_local=row["store_name_local"] if row["store_name_local"] is not None else "N/A",
                bu_key=row["bu_key"] if row["bu_key"] is not None else "N/A",
                area_manager=row["area_manager"] if row["area_manager"] is not None else "N/A",
                store_format=row["store_format"] if row["store_format"] is not None else "N/A",
                store_type=row["store_type"] if row["store_type"] is not None else "N/A",
                operations_controller=row["operations_controller"] if row["operations_controller"] is not None else "N/A",
                regional_manager=row["regional_manager"] if row["regional_manager"] is not None else "N/A",
                px=row["px"] if row["px"] is not None else "N/A",
                csr=row["csr"] if row["csr"] is not None else "N/A",
                dr=row["dr"] if row["dr"] is not None else "N/A",
                mag_type=row["mag_type"] if row["mag_type"] is not None else "N/A",
                cf_grouping=row["cf_grouping"] if row["cf_grouping"] is not None else "N/A",
                store_brand=row["store_brand"] if row["store_brand"] is not None else "N/A",
                competitor=row["competitor"] if row["competitor"] is not None else "N/A",
                region=row["region"] if row["region"] is not None else "N/A",
                area=row["area"] if row["area"] is not None else "N/A",
                territory=row["territory"] if row["territory"] is not None else "N/A",
                toh=row["toh"] if row["toh"] is not None else "N/A",
                district=row["district"] if row["district"] is not None else "N/A",
                city=row["city"] if row["city"] is not None else "N/A",
                operations_manager=row["operations_manager"] if row["operations_manager"] is not None else "N/A",
                district_manager=row["district_manager"] if row["district_manager"] is not None else "N/A",
                sic=row["sic"] if row["sic"] is not None else "N/A",
                tech_life_type=row["tech_life_type"] if row["tech_life_type"] is not None else "N/A",
                operation_manager_tl=row["operation_manager_tl"] if row["operation_manager_tl"] is not None else "N/A",
                region_manager_tl=row["region_manager_tl"] if row["region_manager_tl"] is not None else "N/A",
                relocation=row["relocation"] if row["relocation"] is not None else "N/A",
                latitude=row["latitude"] if row["latitude"] is not None else "N/A",
                longitude=row["longitude"] if row["longitude"] is not None else "N/A",
                store_open_date=datetime.strptime(row["store_open_date"], "%Y-%m-%d").date() if row["store_open_date"] else None,
                store_close_date=datetime.strptime(row["store_close_date"], "%Y-%m-%d").date() if row["store_close_date"] else None,
                is_closed=True if row["is_closed"] == "True" else False,
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