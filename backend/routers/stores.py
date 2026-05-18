from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from utils.database import get_db
from models.Store import Store
from utils.security import get_current_user
from utils.conditionFilter import (
    FilterRequest,
    get_filter_params,
    build_store_filter_conditions,
)
from pydantic import BaseModel
from typing import Optional, List, Annotated
from datetime import datetime, date
import pandas as pd
import numpy as np
import os
import asyncio
from io import StringIO

router = APIRouter(
    prefix="/stores",
    tags=["stores"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class StoreResponse(BaseModel):
    store_key: int
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
    province: Optional[str] = None
    territory: Optional[str] = None
    toh: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    operations_manager: Optional[str] = None
    district_manager: Optional[str] = None
    sic: Optional[str] = None
    # ALTER TABLE stores ADD COLUMN soc VARCHAR(100) NULL;
    soc: Optional[str] = None
    tech_life_type: Optional[str] = None
    operation_manager_tl: Optional[str] = None
    region_manager_tl: Optional[str] = None
    relocation: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    store_open_date: Optional[date] = None
    store_close_date: Optional[date] = None
    is_closed: bool


@router.get("/export")
async def export_stores_csv(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    filter_dict = filter_params.model_dump()
    conditions = build_store_filter_conditions(filter_dict)
    stores = db.query(Store).filter(and_(*conditions)).order_by(Store.store_key).all()

    headers = [
        "store_key", "store_name_english", "store_name_local", "bu_key",
        "area_manager", "store_format", "store_type", "operations_controller",
        "regional_manager", "px", "csr", "dr", "mag_type", "cf_grouping",
        "store_brand", "competitor", "region", "area", "province", "territory",
        "toh", "district", "city", "operations_manager", "district_manager",
        "sic", "soc", "tech_life_type", "operation_manager_tl", "region_manager_tl",
        "relocation", "latitude", "longitude", "store_open_date", "store_close_date",
        "is_closed",
    ]

    output = StringIO()
    output.write(",".join(headers) + "\n")
    for store in stores:
        row = store.to_dict()
        output.write(",".join(str(row.get(h, "") or "") for h in headers) + "\n")
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=stores.csv"},
    )


@router.get("/")
async def get_stores(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[StoreResponse]:
    filter_dict = filter_params.model_dump()
    conditions = build_store_filter_conditions(filter_dict)
    stores = db.query(Store).filter(and_(*conditions)).all()
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
            province=store.province,
            territory=store.territory,
            toh=store.toh,
            district=store.district,
            city=store.city,
            operations_manager=store.operations_manager,
            district_manager=store.district_manager,
            sic=store.sic,
            soc=store.soc,
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
        province=store.province,
        territory=store.territory,
        toh=store.toh,
        district=store.district,
        city=store.city,
        operations_manager=store.operations_manager,
        district_manager=store.district_manager,
        sic=store.sic,
        soc=store.soc,
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
    province: Optional[str] = None
    territory: Optional[str] = None
    toh: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    operations_manager: Optional[str] = None
    district_manager: Optional[str] = None
    sic: Optional[str] = None
    soc: Optional[str] = None
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
        province=create_store_request.province,
        territory=create_store_request.territory,
        toh=create_store_request.toh,
        district=create_store_request.district,
        city=create_store_request.city,
        operations_manager=create_store_request.operations_manager,
        district_manager=create_store_request.district_manager,
        sic=create_store_request.sic,
        soc=create_store_request.soc,
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
        province=store.province,
        territory=store.territory,
        toh=store.toh,
        district=store.district,
        city=store.city,
        operations_manager=store.operations_manager,
        district_manager=store.district_manager,
        sic=store.sic,
        soc=store.soc,
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
    
    def process_csv_file():
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
                    store_name_english=row.get("store_name_english"),
                    store_name_local=row.get("store_name_local"),
                    bu_key=row.get("bu_key"),
                    area_manager=row.get("area_manager"),
                    store_format=row.get("store_format"),
                    store_type=row.get("store_type"),
                    operations_controller=row.get("operations_controller"),
                    regional_manager=row.get("regional_manager"),
                    px=row.get("px"),
                    csr=row.get("csr"),
                    dr=row.get("dr"),
                    mag_type=row.get("mag_type"),
                    cf_grouping=row.get("cf_grouping"),
                    store_brand=row.get("store_brand"),
                    competitor=row.get("competitor"),
                    region=row.get("region"),
                    area=row.get("area"),
                    province=row.get("province"),
                    territory=row.get("territory"),
                    toh=row.get("toh"),
                    district=row.get("district"),
                    city=row.get("city"),
                    operations_manager=row.get("operations_manager"),
                    district_manager=row.get("district_manager"),
                    sic=row.get("sic"),
                    soc=row.get("soc"),
                    tech_life_type=row.get("tech_life_type"),
                    operation_manager_tl=row.get("operation_manager_tl"),
                    region_manager_tl=row.get("region_manager_tl"),
                    relocation=row.get("relocation"),
                    latitude=row.get("latitude"),
                    longitude=row.get("longitude"),
                    store_open_date=datetime.strptime(row.get("store_open_date"), "%Y-%m-%d").date() if row.get("store_open_date") else None,
                    store_close_date=datetime.strptime(row.get("store_close_date"), "%Y-%m-%d").date() if row.get("store_close_date") else None,
                    is_closed=True if row.get("is_closed") == "True" else False,
                )
                db.merge(store)
            
            db.commit()
            return {"message": "Stores upserted successfully"}
        except Exception as e:
            db.rollback()
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
            raise e
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
    
    try:
        result = await asyncio.to_thread(process_csv_file)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV file: {str(e)}")