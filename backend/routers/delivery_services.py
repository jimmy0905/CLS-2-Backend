from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.database import get_db
from models.DeliveryService import DeliveryService
from utils.security import get_current_user, require_admin
from pydantic import BaseModel

router = APIRouter(
    prefix="/delivery_services",
    tags=["delivery_services"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class DeliveryServiceResponse(BaseModel):
    id: int
    name: str


@router.get("/")
async def get_delivery_services(db: Session = Depends(get_db)):
    delivery_services = db.query(DeliveryService).all()
    return delivery_services


class CreateDeliveryServiceRequest(BaseModel):
    name: str


@router.post("/")
async def create_delivery_service(
    create_delivery_service_request: CreateDeliveryServiceRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    # Check if delivery service already exists
    delivery_service = (
        db.query(DeliveryService)
        .filter(DeliveryService.name == create_delivery_service_request.name)
        .first()
    )
    if delivery_service:
        raise HTTPException(status_code=400, detail="Delivery service already exists")
    delivery_service = DeliveryService(name=create_delivery_service_request.name)
    db.add(delivery_service)
    db.commit()
    db.refresh(delivery_service)
    return delivery_service


class UpdateDeliveryServiceRequest(BaseModel):
    name: str


@router.put("/{delivery_service_id}")
async def update_delivery_service(
    delivery_service_id: int,
    update_delivery_service_request: UpdateDeliveryServiceRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    delivery_service = (
        db.query(DeliveryService)
        .filter(DeliveryService.id == delivery_service_id)
        .first()
    )
    if not delivery_service:
        raise HTTPException(status_code=404, detail="Delivery service not found")
    delivery_service.name = update_delivery_service_request.name
    db.commit()
    db.refresh(delivery_service)
    return delivery_service


@router.delete("/{delivery_service_id}")
async def delete_delivery_service(
    delivery_service_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    delivery_service = (
        db.query(DeliveryService)
        .filter(DeliveryService.id == delivery_service_id)
        .first()
    )
    if not delivery_service:
        raise HTTPException(status_code=404, detail="Delivery service not found")
    db.delete(delivery_service)
    db.commit()
    return {"message": f"Delivery service {delivery_service.name} deleted successfully"}


@router.get("/{delivery_service_id}")
async def get_delivery_service(delivery_service_id: int, db: Session = Depends(get_db)):
    delivery_service = (
        db.query(DeliveryService)
        .filter(DeliveryService.id == delivery_service_id)
        .first()
    )
    if not delivery_service:
        raise HTTPException(status_code=404, detail="Delivery service not found")
    return delivery_service
