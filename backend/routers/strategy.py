from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from models.db_config import get_db
from models.User import User
from utils.conditionFilter import build_survey_query, build_optimized_query
from utils.security import get_current_user
from models.Survey import Survey
from typing import List, Optional
from utils.llm import generate_strategy
from pydantic import BaseModel, Field
from models.Store import Store
from sqlalchemy import or_, func, case
from models.District import District
from models.Region import Region
from models.Source import Source
from utils.conditionFilter import FilterRequest, get_filter_params

router = APIRouter(
    prefix="/strategy",
    tags=["strategy"],
    dependencies=[Depends(get_current_user)],
)


class DistrictResponse(BaseModel):
    id: int
    name: str


class SourceResponse(BaseModel):
    id: int
    name: str


class RegionResponse(BaseModel):
    id: int
    name: str


class StoreResponse(BaseModel):
    id: int
    name: str
    district: DistrictResponse
    region: RegionResponse
    source: SourceResponse


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
            func.count(case((Survey.sentiment == "Neutral", Survey.id))).label(
                "neutral_count"
            ),
            func.count(case((Survey.sentiment == "Positive", Survey.id))).label(
                "positive_count"
            ),
            func.count(case((Survey.sentiment == "Negative", Survey.id))).label(
                "negative_count"
            ),
        )
        .group_by(Store.id, Store.name)
        .all()
    )

    # Get store details for the stores we found
    store_ids = [r.store_id for r in sentiment_results]
    store_details = (
        db.query(Store)
        .filter(Store.id.in_(store_ids))
        .join(District, Store.district_id == District.id)
        .join(Region, Store.region_id == Region.id)
        .join(Source, Store.source_id == Source.id)
        .with_entities(
            Store.id.label("store_id"),
            District.id.label("district_id"),
            District.name.label("district_name"),
            Region.id.label("region_id"),
            Region.name.label("region_name"),
            Source.id.label("source_id"),
            Source.name.label("source_name"),
        )
        .all()
    )

    # Create a lookup dictionary for store details
    store_details_map = {d.store_id: d for d in store_details}

    store_with_sentiment = []
    for store in sentiment_results:
        details = store_details_map[store.store_id]
        score = (store.positive_count - store.negative_count) / (
            store.positive_count + store.negative_count + store.neutral_count
        )
        store_with_sentiment.append(
            TopKPerformanceStoresResponse(
                store={
                    "id": store.store_id,
                    "name": store.store_name,
                    "district": {
                        "id": details.district_id,
                        "name": details.district_name,
                    },
                    "region": {
                        "id": details.region_id,
                        "name": details.region_name,
                    },
                    "source": {
                        "id": details.source_id,
                        "name": details.source_name,
                    },
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
        "sentiments": ["Positive"],
    }
    filtered_query = build_survey_query(db.query(Survey).distinct(), filter_dict)
    surveys = filtered_query.all()
    strategy, _ = await generate_strategy(surveys)
    return strategy


class TopKPerformanceRegionsResponse(BaseModel):
    region: RegionResponse
    score: float
    positive_count: int
    negative_count: int
    neutral_count: int


@router.get("/get_top_k_performance_regions")
async def get_top_k_performance_regions(
    db: Session = Depends(get_db),
    filter_params: FilterRequest = Depends(get_filter_params),
    k: int = Query(
        default=10,
        description="The number of top performing regions to return",
    ),
):
    filter_dict = filter_params.model_dump()
    sentiment_query, sentiment_joins = build_optimized_query(db, filter_dict)
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)
    if "region" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Region, Store.region_id == Region.id)
    sentiment_results = (
        sentiment_query.with_entities(
            Region.id.label("region_id"),
            Region.name.label("region_name"),
            func.count(case((Survey.sentiment == "Neutral", Survey.id))).label(
                "neutral_count"
            ),
            func.count(case((Survey.sentiment == "Positive", Survey.id))).label(
                "positive_count"
            ),
            func.count(case((Survey.sentiment == "Negative", Survey.id))).label(
                "negative_count"
            ),
        )
        .group_by(Region.id, Region.name)
        .all()
    )
    region_with_sentiment = []
    for region in sentiment_results:
        score = (region.positive_count - region.negative_count) / (
            region.positive_count + region.negative_count + region.neutral_count
        )
        region_with_sentiment.append(
            TopKPerformanceRegionsResponse(
                region={
                    "id": region.region_id,
                    "name": region.region_name,
                },
                score=score,
                positive_count=region.positive_count,
                negative_count=region.negative_count,
                neutral_count=region.neutral_count,
            )
        )
    region_with_sentiment.sort(key=lambda x: x.score, reverse=True)
    region_with_sentiment = region_with_sentiment[:k]
    return region_with_sentiment


class StrategyByRegionIdsRequest(BaseModel):
    region_ids: List[str] = Field(
        default_factory=list,
        description="The region ids to get the strategy",
    )


@router.post("/get_strategy_for_region_by_ids")
async def get_strategy_for_region_by_ids(
    request: StrategyByRegionIdsRequest,
    db: Session = Depends(get_db),
) -> str:
    filter_dict = {
        "region_ids": request.region_ids,
        "sentiments": ["Positive"],
    }
    filtered_query = build_survey_query(db.query(Survey).distinct(), filter_dict)
    surveys = filtered_query.all()
    strategy, _ = await generate_strategy(surveys)
    return strategy
