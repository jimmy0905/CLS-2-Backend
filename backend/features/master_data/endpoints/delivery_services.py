from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from features.master_data.dto import (
    CreateDeliveryServiceRequest,
    UpdateDeliveryServiceRequest,
)
from features.master_data.service import delivery_service_service
from infrastructure.database.session import get_db
from features.identity.service.security import get_current_actor, require_admin

router = APIRouter(
    prefix="/delivery_services",
    tags=["delivery_services"],
    dependencies=[Depends(get_db), Depends(get_current_actor)],
)


@router.post("/")
async def create_delivery_service(
    create_delivery_service_request: CreateDeliveryServiceRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return delivery_service_service(db).create(create_delivery_service_request.name)


@router.put("/{delivery_service_id}")
async def update_delivery_service(
    delivery_service_id: int,
    update_delivery_service_request: UpdateDeliveryServiceRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return delivery_service_service(db).update(
        delivery_service_id, update_delivery_service_request.name
    )


@router.delete("/{delivery_service_id}")
async def delete_delivery_service(
    delivery_service_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return {"message": delivery_service_service(db).delete(delivery_service_id)}
