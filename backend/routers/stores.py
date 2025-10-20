from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from utils.database import get_db
from models.Store import Store
from models.Hierarchy import Hierarchy
from utils.security import get_current_user
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(
    prefix="/stores",
    tags=["stores"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class HierarchyResponse(BaseModel):
    id: int
    name: str
    level: int
    parent_id: Optional[int] = None


class StoreResponse(BaseModel):
    id: int
    name: str
    hierarchy_level_1: Optional[HierarchyResponse] = None
    hierarchy_level_2: Optional[HierarchyResponse] = None
    hierarchy_level_3: Optional[HierarchyResponse] = None
    hierarchy_level_4: Optional[HierarchyResponse] = None
    hierarchy_level_5: Optional[HierarchyResponse] = None
    is_active: bool


@router.get("/")
async def get_stores(db: Session = Depends(get_db)) -> List[StoreResponse]:
    stores = (
        db.query(Store)
        .options(
            joinedload(Store.hierarchy_level_1),
            joinedload(Store.hierarchy_level_2),
            joinedload(Store.hierarchy_level_3),
            joinedload(Store.hierarchy_level_4),
            joinedload(Store.hierarchy_level_5),
        )
        .all()
    )
    return [
        StoreResponse(
            id=store.id,
            name=store.name,
            hierarchy_level_1=HierarchyResponse(
                id=store.hierarchy_level_1.id,
                name=store.hierarchy_level_1.name,
                level=store.hierarchy_level_1.level,
                parent_id=store.hierarchy_level_1.parent_id,
            ) if store.hierarchy_level_1 else None,
            hierarchy_level_2=HierarchyResponse(
                id=store.hierarchy_level_2.id,
                name=store.hierarchy_level_2.name,
                level=store.hierarchy_level_2.level,
                parent_id=store.hierarchy_level_2.parent_id,
            ) if store.hierarchy_level_2 else None,
            hierarchy_level_3=HierarchyResponse(
                id=store.hierarchy_level_3.id,
                name=store.hierarchy_level_3.name,
                level=store.hierarchy_level_3.level,
                parent_id=store.hierarchy_level_3.parent_id,
            ) if store.hierarchy_level_3 else None,
            hierarchy_level_4=HierarchyResponse(
                id=store.hierarchy_level_4.id,
                name=store.hierarchy_level_4.name,
                level=store.hierarchy_level_4.level,
                parent_id=store.hierarchy_level_4.parent_id,
            ) if store.hierarchy_level_4 else None,
            hierarchy_level_5=HierarchyResponse(
                id=store.hierarchy_level_5.id,
                name=store.hierarchy_level_5.name,
                level=store.hierarchy_level_5.level,
                parent_id=store.hierarchy_level_5.parent_id,
            ) if store.hierarchy_level_5 else None,
            is_active=store.is_active,
        )
        for store in stores
    ]


@router.get("/{store_id}")
async def get_store(store_id: int, db: Session = Depends(get_db)) -> StoreResponse:
    store = (
        db.query(Store)
        .options(
            joinedload(Store.hierarchy_level_1),
            joinedload(Store.hierarchy_level_2),
            joinedload(Store.hierarchy_level_3),
            joinedload(Store.hierarchy_level_4),
            joinedload(Store.hierarchy_level_5),
        )
        .filter(Store.id == store_id)
        .first()
    )
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return StoreResponse(
        id=store.id,
        name=store.name,
        hierarchy_level_1=HierarchyResponse(
            id=store.hierarchy_level_1.id,
            name=store.hierarchy_level_1.name,
            level=store.hierarchy_level_1.level,
            parent_id=store.hierarchy_level_1.parent_id,
        ) if store.hierarchy_level_1 else None,
        hierarchy_level_2=HierarchyResponse(
            id=store.hierarchy_level_2.id,
            name=store.hierarchy_level_2.name,
            level=store.hierarchy_level_2.level,
            parent_id=store.hierarchy_level_2.parent_id,
        ) if store.hierarchy_level_2 else None,
        hierarchy_level_3=HierarchyResponse(
            id=store.hierarchy_level_3.id,
            name=store.hierarchy_level_3.name,
            level=store.hierarchy_level_3.level,
            parent_id=store.hierarchy_level_3.parent_id,
        ) if store.hierarchy_level_3 else None,
        hierarchy_level_4=HierarchyResponse(
            id=store.hierarchy_level_4.id,
            name=store.hierarchy_level_4.name,
            level=store.hierarchy_level_4.level,
            parent_id=store.hierarchy_level_4.parent_id,
        ) if store.hierarchy_level_4 else None,
        hierarchy_level_5=HierarchyResponse(
            id=store.hierarchy_level_5.id,
            name=store.hierarchy_level_5.name,
            level=store.hierarchy_level_5.level,
            parent_id=store.hierarchy_level_5.parent_id,
        ) if store.hierarchy_level_5 else None,
        is_active=store.is_active,
    )


class CreateStoreRequest(BaseModel):
    store_id: int
    name: str
    hierarchy_level_1_id: Optional[int] = None
    hierarchy_level_1_name: Optional[str] = None
    hierarchy_level_2_id: Optional[int] = None
    hierarchy_level_2_name: Optional[str] = None
    hierarchy_level_3_id: Optional[int] = None
    hierarchy_level_3_name: Optional[str] = None
    hierarchy_level_4_id: Optional[int] = None
    hierarchy_level_4_name: Optional[str] = None
    hierarchy_level_5_id: Optional[int] = None
    hierarchy_level_5_name: Optional[str] = None


@router.post("/")
async def create_store(
    create_store_request: CreateStoreRequest, db: Session = Depends(get_db)
) -> StoreResponse:
    # Helper function to validate hierarchy level
    def validate_hierarchy_level(level_id, level_name, level_num):
        if level_id is not None and level_name is not None:
            raise HTTPException(
                status_code=400,
                detail=f"Hierarchy level {level_num} id and name cannot be provided together",
            )
        
        hierarchy = None
        if level_id:
            hierarchy = db.query(Hierarchy).filter(Hierarchy.id == level_id).first()
            if not hierarchy:
                raise HTTPException(status_code=404, detail=f"Hierarchy level {level_num} not found")
        elif level_name:
            hierarchy = db.query(Hierarchy).filter(Hierarchy.name == level_name).first()
            if not hierarchy:
                raise HTTPException(status_code=404, detail=f"Hierarchy level {level_num} not found")
        
        return hierarchy

    # If store id is provided, check if store exists
    if create_store_request.store_id:
        store = db.query(Store).filter(Store.id == create_store_request.store_id).first()
        if store:
            raise HTTPException(status_code=400, detail="Store id already exists")
    
    # Validate hierarchy levels
    hierarchy_1 = validate_hierarchy_level(
        create_store_request.hierarchy_level_1_id,
        create_store_request.hierarchy_level_1_name,
        1
    )
    hierarchy_2 = validate_hierarchy_level(
        create_store_request.hierarchy_level_2_id,
        create_store_request.hierarchy_level_2_name,
        2
    )
    hierarchy_3 = validate_hierarchy_level(
        create_store_request.hierarchy_level_3_id,
        create_store_request.hierarchy_level_3_name,
        3
    )
    hierarchy_4 = validate_hierarchy_level(
        create_store_request.hierarchy_level_4_id,
        create_store_request.hierarchy_level_4_name,
        4
    )
    hierarchy_5 = validate_hierarchy_level(
        create_store_request.hierarchy_level_5_id,
        create_store_request.hierarchy_level_5_name,
        5
    )

    store = Store(
        id=create_store_request.store_id,
        name=create_store_request.name,
        hierarchy_level_1_id=hierarchy_1.id if hierarchy_1 else None,
        hierarchy_level_2_id=hierarchy_2.id if hierarchy_2 else None,
        hierarchy_level_3_id=hierarchy_3.id if hierarchy_3 else None,
        hierarchy_level_4_id=hierarchy_4.id if hierarchy_4 else None,
        hierarchy_level_5_id=hierarchy_5.id if hierarchy_5 else None,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    return StoreResponse(
        id=store.id,
        name=store.name,
        hierarchy_level_1=HierarchyResponse(
            id=store.hierarchy_level_1.id,
            name=store.hierarchy_level_1.name,
            level=store.hierarchy_level_1.level,
            parent_id=store.hierarchy_level_1.parent_id,
        ) if store.hierarchy_level_1 else None,
        hierarchy_level_2=HierarchyResponse(
            id=store.hierarchy_level_2.id,
            name=store.hierarchy_level_2.name,
            level=store.hierarchy_level_2.level,
            parent_id=store.hierarchy_level_2.parent_id,
        ) if store.hierarchy_level_2 else None,
        hierarchy_level_3=HierarchyResponse(
            id=store.hierarchy_level_3.id,
            name=store.hierarchy_level_3.name,
            level=store.hierarchy_level_3.level,
            parent_id=store.hierarchy_level_3.parent_id,
        ) if store.hierarchy_level_3 else None,
        hierarchy_level_4=HierarchyResponse(
            id=store.hierarchy_level_4.id,
            name=store.hierarchy_level_4.name,
            level=store.hierarchy_level_4.level,
            parent_id=store.hierarchy_level_4.parent_id,
        ) if store.hierarchy_level_4 else None,
        hierarchy_level_5=HierarchyResponse(
            id=store.hierarchy_level_5.id,
            name=store.hierarchy_level_5.name,
            level=store.hierarchy_level_5.level,
            parent_id=store.hierarchy_level_5.parent_id,
        ) if store.hierarchy_level_5 else None,
        is_active=store.is_active,
    )


class UpdateStoreRequest(BaseModel):
    name: Optional[str] = None
    hierarchy_level_1_id: Optional[int] = None
    hierarchy_level_2_id: Optional[int] = None
    hierarchy_level_3_id: Optional[int] = None
    hierarchy_level_4_id: Optional[int] = None
    hierarchy_level_5_id: Optional[int] = None
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
    
    # Update hierarchy levels
    if update_store_request.hierarchy_level_1_id is not None:
        hierarchy = db.query(Hierarchy).filter(Hierarchy.id == update_store_request.hierarchy_level_1_id).first()
        if not hierarchy:
            raise HTTPException(status_code=404, detail="Hierarchy level 1 not found")
        store.hierarchy_level_1_id = update_store_request.hierarchy_level_1_id
    
    if update_store_request.hierarchy_level_2_id is not None:
        hierarchy = db.query(Hierarchy).filter(Hierarchy.id == update_store_request.hierarchy_level_2_id).first()
        if not hierarchy:
            raise HTTPException(status_code=404, detail="Hierarchy level 2 not found")
        store.hierarchy_level_2_id = update_store_request.hierarchy_level_2_id
    
    if update_store_request.hierarchy_level_3_id is not None:
        hierarchy = db.query(Hierarchy).filter(Hierarchy.id == update_store_request.hierarchy_level_3_id).first()
        if not hierarchy:
            raise HTTPException(status_code=404, detail="Hierarchy level 3 not found")
        store.hierarchy_level_3_id = update_store_request.hierarchy_level_3_id
    
    if update_store_request.hierarchy_level_4_id is not None:
        hierarchy = db.query(Hierarchy).filter(Hierarchy.id == update_store_request.hierarchy_level_4_id).first()
        if not hierarchy:
            raise HTTPException(status_code=404, detail="Hierarchy level 4 not found")
        store.hierarchy_level_4_id = update_store_request.hierarchy_level_4_id
    
    if update_store_request.hierarchy_level_5_id is not None:
        hierarchy = db.query(Hierarchy).filter(Hierarchy.id == update_store_request.hierarchy_level_5_id).first()
        if not hierarchy:
            raise HTTPException(status_code=404, detail="Hierarchy level 5 not found")
        store.hierarchy_level_5_id = update_store_request.hierarchy_level_5_id
    
    if update_store_request.is_active is not None:
        store.is_active = update_store_request.is_active
    
    db.commit()
    db.refresh(store)
    return StoreResponse(
        id=store.id,
        name=store.name,
        hierarchy_level_1=HierarchyResponse(
            id=store.hierarchy_level_1.id,
            name=store.hierarchy_level_1.name,
            level=store.hierarchy_level_1.level,
            parent_id=store.hierarchy_level_1.parent_id,
        ) if store.hierarchy_level_1 else None,
        hierarchy_level_2=HierarchyResponse(
            id=store.hierarchy_level_2.id,
            name=store.hierarchy_level_2.name,
            level=store.hierarchy_level_2.level,
            parent_id=store.hierarchy_level_2.parent_id,
        ) if store.hierarchy_level_2 else None,
        hierarchy_level_3=HierarchyResponse(
            id=store.hierarchy_level_3.id,
            name=store.hierarchy_level_3.name,
            level=store.hierarchy_level_3.level,
            parent_id=store.hierarchy_level_3.parent_id,
        ) if store.hierarchy_level_3 else None,
        hierarchy_level_4=HierarchyResponse(
            id=store.hierarchy_level_4.id,
            name=store.hierarchy_level_4.name,
            level=store.hierarchy_level_4.level,
            parent_id=store.hierarchy_level_4.parent_id,
        ) if store.hierarchy_level_4 else None,
        hierarchy_level_5=HierarchyResponse(
            id=store.hierarchy_level_5.id,
            name=store.hierarchy_level_5.name,
            level=store.hierarchy_level_5.level,
            parent_id=store.hierarchy_level_5.parent_id,
        ) if store.hierarchy_level_5 else None,
        is_active=store.is_active,
    )


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
