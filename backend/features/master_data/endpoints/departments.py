from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from features.master_data.dto import (
    CreateDepartmentRequest,
    UpdateDepartmentRequest,
)
from features.master_data.service import department_service
from infrastructure.database.session import get_db
from features.identity.service.security import get_current_actor

router = APIRouter(
    prefix="/departments",
    tags=["departments"],
    dependencies=[Depends(get_db), Depends(get_current_actor)],
)


@router.get("/")
async def get_departments(db: Session = Depends(get_db)):
    return department_service(db).list()


@router.get("/{department_id}")
async def get_department(department_id: int, db: Session = Depends(get_db)):
    return department_service(db).get(department_id)


@router.post("/")
async def create_department(
    create_department_request: CreateDepartmentRequest, db: Session = Depends(get_db)
):
    return department_service(db).create(create_department_request.name)


@router.put("/{department_id}")
async def update_department(
    department_id: int,
    update_department_request: UpdateDepartmentRequest,
    db: Session = Depends(get_db),
):
    return department_service(db).update(department_id, update_department_request.name)


@router.delete("/{department_id}")
async def delete_department(department_id: int, db: Session = Depends(get_db)):
    department_service(db).delete(department_id)
    return {"message": "Department deleted successfully"}
