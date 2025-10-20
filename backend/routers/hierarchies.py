from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from utils.database import get_db
from models.Hierarchy import Hierarchy
from utils.security import get_current_user
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(
    prefix="/hierarchies",
    tags=["hierarchies"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class HierarchyResponse(BaseModel):
    id: int
    name: str
    level: int


@router.get("/")
async def get_hierarchies(
    level: Optional[int] = Query(None, description="Filter by hierarchy level (1-5)"),
    db: Session = Depends(get_db),
) -> List[HierarchyResponse]:
    query = db.query(Hierarchy)
    if level is not None:
        query = query.filter(Hierarchy.level == level)
    hierarchies = query.all()
    return [
        HierarchyResponse(
            id=hierarchy.id,
            name=hierarchy.name,
            level=hierarchy.level,
        )
        for hierarchy in hierarchies
    ]


@router.get("/{hierarchy_id}")
async def get_hierarchy(
    hierarchy_id: int, db: Session = Depends(get_db)
) -> HierarchyResponse:
    hierarchy = db.query(Hierarchy).filter(Hierarchy.id == hierarchy_id).first()
    if not hierarchy:
        raise HTTPException(status_code=404, detail="Hierarchy not found")
    return HierarchyResponse(
        id=hierarchy.id,
        name=hierarchy.name,
        level=hierarchy.level,
    )


class CreateHierarchyRequest(BaseModel):
    name: str
    level: int


@router.post("/")
async def create_hierarchy(
    create_hierarchy_request: CreateHierarchyRequest, db: Session = Depends(get_db)
) -> HierarchyResponse:
    # Validate level
    if create_hierarchy_request.level not in [1, 2, 3, 4, 5]:
        raise HTTPException(
            status_code=400, detail="Level must be between 1 and 5"
        )
    
    # Check if name already exists
    existing = (
        db.query(Hierarchy)
        .filter(Hierarchy.name == create_hierarchy_request.name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Hierarchy name already exists")
    
    hierarchy = Hierarchy(
        name=create_hierarchy_request.name,
        level=create_hierarchy_request.level,
    )
    db.add(hierarchy)
    db.commit()
    db.refresh(hierarchy)
    return HierarchyResponse(
        id=hierarchy.id,
        name=hierarchy.name,
        level=hierarchy.level,
    )


class UpdateHierarchyRequest(BaseModel):
    name: Optional[str] = None
    level: Optional[int] = None


@router.put("/{hierarchy_id}")
async def update_hierarchy(
    hierarchy_id: int,
    update_hierarchy_request: UpdateHierarchyRequest,
    db: Session = Depends(get_db),
):
    hierarchy = db.query(Hierarchy).filter(Hierarchy.id == hierarchy_id).first()
    if not hierarchy:
        raise HTTPException(status_code=404, detail="Hierarchy not found")
    
    if update_hierarchy_request.name:
        # Check if new name already exists
        existing = (
            db.query(Hierarchy)
            .filter(
                Hierarchy.name == update_hierarchy_request.name,
                Hierarchy.id != hierarchy_id
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Hierarchy name already exists")
        hierarchy.name = update_hierarchy_request.name
    
    if update_hierarchy_request.level is not None:
        if update_hierarchy_request.level not in [1, 2, 3, 4, 5]:
            raise HTTPException(
                status_code=400, detail="Level must be between 1 and 5"
            )
        hierarchy.level = update_hierarchy_request.level
    
    db.commit()
    db.refresh(hierarchy)
    return HierarchyResponse(
        id=hierarchy.id,
        name=hierarchy.name,
        level=hierarchy.level,
    )


@router.delete("/{hierarchy_id}")
async def delete_hierarchy(
    hierarchy_id: int,
    db: Session = Depends(get_db),
):
    hierarchy = db.query(Hierarchy).filter(Hierarchy.id == hierarchy_id).first()
    if not hierarchy:
        raise HTTPException(status_code=404, detail="Hierarchy not found")
    
    # Check if any stores reference this hierarchy
    from models.Store import Store
    stores_using = db.query(Store).filter(
        (Store.hierarchy_level_1_id == hierarchy_id) |
        (Store.hierarchy_level_2_id == hierarchy_id) |
        (Store.hierarchy_level_3_id == hierarchy_id) |
        (Store.hierarchy_level_4_id == hierarchy_id) |
        (Store.hierarchy_level_5_id == hierarchy_id)
    ).first()
    
    if stores_using:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete hierarchy that is referenced by stores"
        )
    
    db.delete(hierarchy)
    db.commit()
    return {"message": "Hierarchy deleted successfully"}

