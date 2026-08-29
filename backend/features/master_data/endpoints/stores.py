import asyncio
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from features.identity.service.security import get_current_user
from features.master_data.dto import CreateStoreRequest, StoreResponse
from features.master_data.mapper import store_to_dict
from features.master_data.service import store_service
from infrastructure.database.session import get_db
from features.feedback.filtering import (
    FilterRequest,
    build_store_filter_conditions,
    get_filter_params,
)

router = APIRouter(
    prefix="/stores",
    tags=["stores"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


@router.get("/export")
async def export_stores_csv(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    filter_dict = filter_params.model_dump()
    conditions = build_store_filter_conditions(filter_dict)
    stores = store_service(db).list(conditions, ordered=True)

    headers = [
        "store_key",
        "store_name_english",
        "store_name_local",
        "bu_key",
        "area_manager",
        "store_format",
        "store_type",
        "operations_controller",
        "regional_manager",
        "px",
        "csr",
        "dr",
        "mag_type",
        "cf_grouping",
        "store_brand",
        "competitor",
        "region",
        "area",
        "province",
        "territory",
        "toh",
        "district",
        "city",
        "operations_manager",
        "district_manager",
        "sic",
        "soc",
        "tech_life_type",
        "operation_manager_tl",
        "region_manager_tl",
        "relocation",
        "latitude",
        "longitude",
        "store_open_date",
        "store_close_date",
        "is_closed",
    ]

    output = StringIO()
    output.write(",".join(headers) + "\n")
    for store in stores:
        row = store_to_dict(store)
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
) -> list[StoreResponse]:
    filter_dict = filter_params.model_dump()
    conditions = build_store_filter_conditions(filter_dict)
    stores = store_service(db).list(conditions)
    return [StoreResponse(**store_to_dict(store)) for store in stores]


@router.get("/{store_key}")
async def get_store(store_key: int, db: Session = Depends(get_db)) -> StoreResponse:
    return StoreResponse(**store_to_dict(store_service(db).get(store_key)))


@router.post("/")
async def create_store(
    create_store_request: CreateStoreRequest, db: Session = Depends(get_db)
) -> StoreResponse:

    store = store_service(db).create(create_store_request.model_dump())
    return StoreResponse(**store_to_dict(store))


@router.delete("/{store_key}")
async def delete_store(
    store_key: int,
    db: Session = Depends(get_db),
):
    store_service(db).close(store_key)
    return {"message": "Store dseleted successfully"}


@router.post("/upsert_stores_from_csv")
async def upsert_stores_from_csv(
    file: Annotated[UploadFile, File()],
    db: Session = Depends(get_db),
):
    # Check if the file is a CSV file
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="File must be a CSV file")

    try:
        result = await asyncio.to_thread(store_service(db).upsert_csv, file)
        return result
    except Exception as error:
        raise HTTPException(
            status_code=400, detail=f"Invalid CSV file: {error!s}"
        ) from error
