from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from utils.database import get_db
from models.User import User
from utils.conditionFilter import build_survey_query, build_optimized_query
from utils.security import get_current_user
from models.Survey import Survey
from typing import List, Optional
from utils.llm.generate_strategy import (
    generate_store_strategy,
    generate_region_strategy,
)
from pydantic import BaseModel, Field
from models.Store import Store
from models.Hierarchy import Hierarchy
from sqlalchemy import or_, func, case
from utils.conditionFilter import FilterRequest, get_filter_params

router = APIRouter(
    prefix="/strategy",
    tags=["strategy"],
    dependencies=[Depends(get_current_user)],
)


class HierarchyResponse(BaseModel):
    id: int
    name: str
    level: int


class StoreResponse(BaseModel):
    id: int
    name: str
    hierarchy_level_1: Optional[HierarchyResponse] = None
    hierarchy_level_2: Optional[HierarchyResponse] = None
    hierarchy_level_3: Optional[HierarchyResponse] = None
    hierarchy_level_4: Optional[HierarchyResponse] = None
    hierarchy_level_5: Optional[HierarchyResponse] = None


class TopKPerformanceStoresResponse(BaseModel):
    store: StoreResponse
    score: float
    positive_count: int
    negative_count: int
    neutral_count: int


@router.get("/get_top_k_performance_stores")
async def get_top_k_performance_stores(
    db: Session = Depends(get_db),
    filter_params: FilterRequest = Depends(get_filter_params),
    k: int = Query(
        default=10,
        description="The number of top performing stores to return",
    ),
):
    filter_dict = filter_params.model_dump()
    # First get the sentiment counts per store
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)

    sentiment_results = (
        sentiment_query.with_entities(
            Store.id.label("store_id"),
            Store.name.label("store_name"),
            func.count(case((Survey.sentiment == "neutral", Survey.id))).label(
                "neutral_count"
            ),
            func.count(case((Survey.sentiment == "positive", Survey.id))).label(
                "positive_count"
            ),
            func.count(case((Survey.sentiment == "negative", Survey.id))).label(
                "negative_count"
            ),
        )
        .group_by(Store.id, Store.name)
        .all()
    )

    # Get store details for the stores we found
    store_ids = [r.store_id for r in sentiment_results]
    stores = (
        db.query(Store)
        .filter(Store.id.in_(store_ids))
        .options(
            joinedload(Store.hierarchy_level_1),
            joinedload(Store.hierarchy_level_2),
            joinedload(Store.hierarchy_level_3),
            joinedload(Store.hierarchy_level_4),
            joinedload(Store.hierarchy_level_5),
        )
        .all()
    )

    # Create a lookup dictionary for store details
    store_details_map = {s.id: s for s in stores}

    store_with_sentiment = []
    for store in sentiment_results:
        store_obj = store_details_map[store.store_id]
        score = (store.positive_count - store.negative_count) / (
            store.positive_count + store.negative_count + store.neutral_count
        )
        store_with_sentiment.append(
            TopKPerformanceStoresResponse(
                store={
                    "id": store.store_id,
                    "name": store.store_name,
                    "hierarchy_level_1": {
                        "id": store_obj.hierarchy_level_1.id,
                        "name": store_obj.hierarchy_level_1.name,
                        "level": store_obj.hierarchy_level_1.level,
                    } if store_obj.hierarchy_level_1 else None,
                    "hierarchy_level_2": {
                        "id": store_obj.hierarchy_level_2.id,
                        "name": store_obj.hierarchy_level_2.name,
                        "level": store_obj.hierarchy_level_2.level,
                    } if store_obj.hierarchy_level_2 else None,
                    "hierarchy_level_3": {
                        "id": store_obj.hierarchy_level_3.id,
                        "name": store_obj.hierarchy_level_3.name,
                        "level": store_obj.hierarchy_level_3.level,
                    } if store_obj.hierarchy_level_3 else None,
                    "hierarchy_level_4": {
                        "id": store_obj.hierarchy_level_4.id,
                        "name": store_obj.hierarchy_level_4.name,
                        "level": store_obj.hierarchy_level_4.level,
                    } if store_obj.hierarchy_level_4 else None,
                    "hierarchy_level_5": {
                        "id": store_obj.hierarchy_level_5.id,
                        "name": store_obj.hierarchy_level_5.name,
                        "level": store_obj.hierarchy_level_5.level,
                    } if store_obj.hierarchy_level_5 else None,
                },
                score=score,
                positive_count=store.positive_count,
                negative_count=store.negative_count,
                neutral_count=store.neutral_count,
            )
        )
    store_with_sentiment.sort(key=lambda x: x.score, reverse=True)
    store_with_sentiment = store_with_sentiment[:k]
    return store_with_sentiment


class StrategyByStoreIdsRequest(BaseModel):
    store_ids: List[str] = Field(
        default_factory=list,
        description="The store ids to get the strategy",
    )


@router.post("/get_strategy_for_store_by_ids")
async def get_strategy_for_store_by_ids(
    request: StrategyByStoreIdsRequest,
    db: Session = Depends(get_db),
) -> str:
    filter_dict = {
        "store_ids": request.store_ids,
        "sentiments": ["positive"],
    }
    filtered_query, _ = build_optimized_query(db, filter_dict)
    surveys = (
        filtered_query.order_by(func.length(Survey.comment).desc()).limit(30).all()
    )
    strategy, _ = await generate_store_strategy(surveys)
    return strategy


class TopKPerformanceHierarchyResponse(BaseModel):
    hierarchy: HierarchyResponse
    score: float
    positive_count: int
    negative_count: int
    neutral_count: int


@router.get("/get_top_k_performance_hierarchies")
async def get_top_k_performance_hierarchies(
    level: int = Query(..., ge=1, le=5, description="Hierarchy level (1-5)"),
    db: Session = Depends(get_db),
    filter_params: FilterRequest = Depends(get_filter_params),
    k: int = Query(
        default=10,
        description="The number of top performing hierarchies to return",
    ),
):
    filter_dict = filter_params.model_dump()
    
    # Map level to Store hierarchy column
    hierarchy_columns = {
        1: Store.hierarchy_level_1_id,
        2: Store.hierarchy_level_2_id,
        3: Store.hierarchy_level_3_id,
        4: Store.hierarchy_level_4_id,
        5: Store.hierarchy_level_5_id,
    }
    
    hierarchy_col = hierarchy_columns[level]
    
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)
    if f"hierarchy_level_{level}" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Hierarchy, hierarchy_col == Hierarchy.id)
    
    sentiment_results = (
        sentiment_query.with_entities(
            Hierarchy.id.label("hierarchy_id"),
            Hierarchy.name.label("hierarchy_name"),
            Hierarchy.level.label("hierarchy_level"),
            func.count(case((Survey.sentiment == "neutral", Survey.id))).label(
                "neutral_count"
            ),
            func.count(case((Survey.sentiment == "positive", Survey.id))).label(
                "positive_count"
            ),
            func.count(case((Survey.sentiment == "negative", Survey.id))).label(
                "negative_count"
            ),
        )
        .group_by(Hierarchy.id, Hierarchy.name, Hierarchy.level)
        .all()
    )
    hierarchy_with_sentiment = []
    for hierarchy in sentiment_results:
        score = (hierarchy.positive_count - hierarchy.negative_count) / (
            hierarchy.positive_count + hierarchy.negative_count + hierarchy.neutral_count
        )
        hierarchy_with_sentiment.append(
            TopKPerformanceHierarchyResponse(
                hierarchy={
                    "id": hierarchy.hierarchy_id,
                    "name": hierarchy.hierarchy_name,
                    "level": hierarchy.hierarchy_level,
                },
                score=score,
                positive_count=hierarchy.positive_count,
                negative_count=hierarchy.negative_count,
                neutral_count=hierarchy.neutral_count,
            )
        )
    hierarchy_with_sentiment.sort(key=lambda x: x.score, reverse=True)
    hierarchy_with_sentiment = hierarchy_with_sentiment[:k]
    return hierarchy_with_sentiment


class StrategyByHierarchyIdsRequest(BaseModel):
    hierarchy_ids: List[int] = Field(
        default_factory=list,
        description="The hierarchy ids to get the strategy",
    )
    level: int = Field(..., ge=1, le=5, description="Hierarchy level (1-5)")


@router.post("/get_strategy_for_hierarchy_by_ids")
async def get_strategy_for_hierarchy_by_ids(
    request: StrategyByHierarchyIdsRequest,
    db: Session = Depends(get_db),
) -> str:
    filter_dict = {
        f"hierarchy_level_{request.level}_ids": request.hierarchy_ids,
        "sentiments": ["positive"],
    }
    filtered_query, _ = build_optimized_query(db, filter_dict)
    surveys = (
        filtered_query.order_by(func.length(Survey.comment).desc()).limit(30).all()
    )
    strategy, _ = await generate_region_strategy(surveys)
    return strategy
