from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from models.db_config import get_db
from models.Department import Department
from utils.security import get_current_user
from pydantic import BaseModel

router = APIRouter(
    prefix="/departments",
    tags=["departments"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


@router.get("/")
async def get_departments(db: Session = Depends(get_db)):
    departments = db.query(Department).all()
    return departments


@router.get("/{department_id}")
async def get_department(department_id: int, db: Session = Depends(get_db)):
    department = db.query(Department).filter(Department.id == department_id).first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    return department


class CreateDepartmentRequest(BaseModel):
    name: str


@router.post("/")
async def create_department(
    create_department_request: CreateDepartmentRequest, db: Session = Depends(get_db)
):
    # Check if department exists
    department = db.query(Department).filter(Department.name == create_department_request.name).first()
    if department:
        raise HTTPException(status_code=400, detail="Department already exists")
    department = Department(name=create_department_request.name)
    db.add(department)
    db.commit()
    db.refresh(department)
    return department


class UpdateDepartmentRequest(BaseModel):
    name: str


@router.put("/{department_id}")
async def update_department(
    department_id: int,
    update_department_request: UpdateDepartmentRequest,
    db: Session = Depends(get_db),
):
    department = db.query(Department).filter(Department.id == department_id).first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    department.name = update_department_request.name
    db.commit()
    db.refresh(department)
    return department


@router.delete("/{department_id}")
async def delete_department(department_id: int, db: Session = Depends(get_db)):
    department = db.query(Department).filter(Department.id == department_id).first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    db.delete(department)
    db.commit()
    return {"message": "Department deleted successfully"}
