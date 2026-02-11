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
    generate_channel_strategy,
    generate_delivery_service_strategy,
)
from pydantic import BaseModel, Field
from models.Store import Store
from models.Hierarchy import Hierarchy
from models.Channel import Channel
from models.DeliveryService import DeliveryService
from sqlalchemy import or_, func, case
from utils.conditionFilter import FilterRequest, get_filter_params
from models.enum.Sentiment import TopicSentiment

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
    mixed_count: int


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
    sentiment_query, sentiment_joins, _ = build_optimized_query(db, filter_dict)
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)

    sentiment_results = (
        sentiment_query.with_entities(
            Store.id.label("store_id"),
            Store.name.label("store_name"),
            func.count(
                case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id))
            ).label("neutral_count"),
            func.count(
                case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id))
            ).label("positive_count"),
            func.count(
                case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id))
            ).label("negative_count"),
            func.count(
                case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id))
            ).label("mixed_count"),
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
        score = (store.positive_count - store.negative_count + store.mixed_count) / (
            store.positive_count
            + store.negative_count
            + store.neutral_count
            + store.mixed_count
        )
        store_with_sentiment.append(
            TopKPerformanceStoresResponse(
                store={
                    "id": store.store_id,
                    "name": store.store_name,
                    "hierarchy_level_1": (
                        {
                            "id": store_obj.hierarchy_level_1.id,
                            "name": store_obj.hierarchy_level_1.name,
                            "level": store_obj.hierarchy_level_1.level,
                        }
                        if store_obj.hierarchy_level_1
                        else None
                    ),
                    "hierarchy_level_2": (
                        {
                            "id": store_obj.hierarchy_level_2.id,
                            "name": store_obj.hierarchy_level_2.name,
                            "level": store_obj.hierarchy_level_2.level,
                        }
                        if store_obj.hierarchy_level_2
                        else None
                    ),
                    "hierarchy_level_3": (
                        {
                            "id": store_obj.hierarchy_level_3.id,
                            "name": store_obj.hierarchy_level_3.name,
                            "level": store_obj.hierarchy_level_3.level,
                        }
                        if store_obj.hierarchy_level_3
                        else None
                    ),
                    "hierarchy_level_4": (
                        {
                            "id": store_obj.hierarchy_level_4.id,
                            "name": store_obj.hierarchy_level_4.name,
                            "level": store_obj.hierarchy_level_4.level,
                        }
                        if store_obj.hierarchy_level_4
                        else None
                    ),
                    "hierarchy_level_5": (
                        {
                            "id": store_obj.hierarchy_level_5.id,
                            "name": store_obj.hierarchy_level_5.name,
                            "level": store_obj.hierarchy_level_5.level,
                        }
                        if store_obj.hierarchy_level_5
                        else None
                    ),
                },
                score=score,
                positive_count=store.positive_count,
                negative_count=store.negative_count,
                neutral_count=store.neutral_count,
                mixed_count=store.mixed_count,
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
        "topic_sentiments": ["POSITIVE"],
    }
    filtered_query, _, _ = build_optimized_query(db, filter_dict)
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
    mixed_count: int


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

    sentiment_query, sentiment_joins, hierarchy_aliases = build_optimized_query(
        db, filter_dict
    )
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)

    # Check if the requested level's hierarchy join exists, if not, create it
    hierarchy_alias = hierarchy_aliases.get(level)
    if f"hierarchy_level_{level}" not in sentiment_joins:
        from sqlalchemy.orm import aliased

        hierarchy_alias = aliased(Hierarchy)
        sentiment_query = sentiment_query.join(
            hierarchy_alias, hierarchy_col == hierarchy_alias.id
        )

    sentiment_results = (
        sentiment_query.with_entities(
            hierarchy_alias.id.label("hierarchy_id"),
            hierarchy_alias.name.label("hierarchy_name"),
            hierarchy_alias.level.label("hierarchy_level"),
            func.count(
                case((Survey.topic_sentiment == TopicSentiment.NEUTRAL, Survey.id))
            ).label("neutral_count"),
            func.count(
                case((Survey.topic_sentiment == TopicSentiment.POSITIVE, Survey.id))
            ).label("positive_count"),
            func.count(
                case((Survey.topic_sentiment == TopicSentiment.NEGATIVE, Survey.id))
            ).label("negative_count"),
            func.count(
                case((Survey.topic_sentiment == TopicSentiment.MIXED, Survey.id))
            ).label("mixed_count"),
        )
        .group_by(hierarchy_alias.id, hierarchy_alias.name, hierarchy_alias.level)
        .all()
    )
    hierarchy_with_sentiment = []
    for hierarchy in sentiment_results:
        score = (
            hierarchy.positive_count - hierarchy.negative_count + hierarchy.mixed_count
        ) / (
            hierarchy.positive_count
            + hierarchy.negative_count
            + hierarchy.neutral_count
            + hierarchy.mixed_count
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
                mixed_count=hierarchy.mixed_count,
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
        "topic_sentiments": ["POSITIVE"],
    }
    filtered_query, _, _ = build_optimized_query(db, filter_dict)
    surveys = (
        filtered_query.order_by(func.length(Survey.comment).desc()).limit(30).all()
    )
    strategy, _ = await generate_region_strategy(surveys)
    return strategy

class ChannelResponse(BaseModel):
    id: int
    name: str

class TopKPerformanceChannelsResponse(BaseModel):
    channel: ChannelResponse
    score: float
    positive_count: int
    negative_count: int
    neutral_count: int


@router.get("/get_top_k_performance_channels")
async def get_top_k_performance_channels(
    db: Session = Depends(get_db),
    filter_params: FilterRequest = Depends(get_filter_params),
    k: int = Query(
        default=10,
        description="The number of top performing channels to return",
    ),
):
    filter_dict = filter_params.model_dump()
    sentiment_query, sentiment_joins, _ = build_optimized_query(db, filter_dict)
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)

    sentiment_results = (
        sentiment_query.with_entities(
            Channel.id.label("channel_id"),
            Channel.name.label("channel_name"),
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
        .group_by(Channel.id, Channel.name)
        .all()
    )
    channel_with_sentiment: List[TopKPerformanceChannelsResponse] = []
    for channel in sentiment_results:
        score = (channel.positive_count - channel.negative_count) / (
            channel.positive_count + channel.negative_count + channel.neutral_count
        )
        channel_with_sentiment.append(
            TopKPerformanceChannelsResponse(
                channel={
                    "id": channel.channel_id,
                    "name": channel.channel_name,
                },
                score=score,
                positive_count=channel.positive_count,
                negative_count=channel.negative_count,
                neutral_count=channel.neutral_count,
            )
        )
    channel_with_sentiment.sort(key=lambda x: x.score, reverse=True)
    channel_with_sentiment = channel_with_sentiment[:k]
    return channel_with_sentiment

class TopKPerformanceByChannelIdsRequest(BaseModel):
    channel_ids: List[int] = Field(
        default_factory=list,
        description="The channel ids to get the top performing channels",
    )

@router.post("/get_strategy_for_channel_by_ids")
async def get_top_k_performance_channels_by_ids(
    request: TopKPerformanceByChannelIdsRequest,
    db: Session = Depends(get_db),
) -> str:
    filter_dict = {
        "channel_ids": request.channel_ids,
        "sentiments": ["positive"],
    }
    filtered_query, _, _ = build_optimized_query(db, filter_dict)
    surveys = (
        filtered_query.order_by(func.length(Survey.comment).desc()).limit(30).all()
    )
    strategy, _ = await generate_channel_strategy(surveys)
    return strategy

class DeliveryServiceResponse(BaseModel):
    id: int
    name: str

class TopKPerformanceDeliveryServicesResponse(BaseModel):
    delivery_service: DeliveryServiceResponse
    score: float
    positive_count: int
    negative_count: int
    neutral_count: int

@router.get("/get_top_k_performance_delivery_services")
async def get_top_k_performance_delivery_services(
    db: Session = Depends(get_db),
    filter_params: FilterRequest = Depends(get_filter_params),
    k: int = Query(
        default=10,
        description="The number of top performing delivery services to return",
    ),
):
    filter_dict = filter_params.model_dump()
    sentiment_query, sentiment_joins, _ = build_optimized_query(db, filter_dict)
    if "store" not in sentiment_joins:
        sentiment_query = sentiment_query.join(Store, Survey.store_id == Store.id)

    sentiment_results = (
        sentiment_query.with_entities(
            DeliveryService.id.label("delivery_service_id"),
            DeliveryService.name.label("delivery_service_name"),
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
        .group_by(DeliveryService.id, DeliveryService.name)
        .all()
    )
    delivery_service_with_sentiment: List[TopKPerformanceDeliveryServicesResponse] = []
    for delivery_service in sentiment_results:
        score = (delivery_service.positive_count - delivery_service.negative_count) / (
            delivery_service.positive_count + delivery_service.negative_count + delivery_service.neutral_count
        )
        delivery_service_with_sentiment.append(
            TopKPerformanceDeliveryServicesResponse(
                delivery_service={
                    "id": delivery_service.delivery_service_id,
                    "name": delivery_service.delivery_service_name,
                },
                score=score,
                positive_count=delivery_service.positive_count,
                negative_count=delivery_service.negative_count,
                neutral_count=delivery_service.neutral_count,
            )
        )
    delivery_service_with_sentiment.sort(key=lambda x: x.score, reverse=True)
    delivery_service_with_sentiment = delivery_service_with_sentiment[:k]
    return delivery_service_with_sentiment 

class TopKPerformanceByDeliveryServiceIdsRequest(BaseModel):
    delivery_service_ids: List[int] = Field(
        default_factory=list,
        description="The delivery service ids to get the top performing delivery services",
    )

@router.post("/get_strategy_for_delivery_service_by_ids")
async def get_top_k_performance_delivery_services_by_ids(
    request: TopKPerformanceByDeliveryServiceIdsRequest,
    db: Session = Depends(get_db),
) -> str:
    filter_dict = {
        "delivery_service_ids": request.delivery_service_ids,
        "sentiments": ["positive"],
    }
    filtered_query, _, _ = build_optimized_query(db, filter_dict)
    surveys = (
        filtered_query.order_by(func.length(Survey.comment).desc()).limit(30).all()
    )
    strategy, _ = await generate_delivery_service_strategy(surveys)
    return strategy

@router.get("/get_strategy_v2")
async def get_strategy_v2(
    db: Session = Depends(get_db),
    filter_params: FilterRequest = Depends(get_filter_params),
) -> dict:
    filter_dict = filter_params.model_dump()
    filtered_query = build_survey_query(db.query(Survey).distinct(), filter_dict)
    def calculate_sentiment(survey):
        """Calculate sentiment based on topics using the same logic as frontend."""
        # Get topics with sentiment from the survey
        topics = [
            {"topic": survey_topic.topic.topic, "sentiment": survey_topic.sentiment}
            for survey_topic in survey.survey_topics
        ]
        
        # Safety check: ensure topics is an array
        if not topics or len(topics) == 0:
            return {"sentiment": "neutral", "score": 0}
        
        # if there are only neutral, return "neutral"
        if all(topic["sentiment"] == "neutral" for topic in topics):
            return {"sentiment": "neutral", "score": 0}
        
        # if there are only positive or neutral, return "positive"
        if all(topic["sentiment"] in ["positive", "neutral"] for topic in topics):
            return {"sentiment": "positive", "score": 1}
        
        # if there are only negative or neutral, return "negative"
        if all(topic["sentiment"] in ["negative", "neutral"] for topic in topics):
            return {"sentiment": "negative", "score": -1}
        
        # if there are both positive and negative, return "mix"
        positive_count = sum(1 for topic in topics if topic["sentiment"] == "positive")
        negative_count = sum(1 for topic in topics if topic["sentiment"] == "negative")
        neutral_count = sum(1 for topic in topics if topic["sentiment"] == "neutral")
        
        if positive_count > 0 and negative_count > 0:
            total_count = positive_count + negative_count + neutral_count
            score = round((positive_count - negative_count) / total_count, 2)
            return {"sentiment": "mix", "score": score}
        
        return {"sentiment": "neutral", "score": 0}

    def format_excel_value(value):
        if value is None:
            return ""
        elif isinstance(value, list):
            return "; ".join(str(item) for item in value)
        elif isinstance(value, datetime):
            return value.isoformat()
        else:
            return str(value)

    def generate_excel_file():
        # Create a workbook and worksheet
        wb = Workbook()
        ws = wb.active
        ws.title = "Surveys"

        # Define headers
        headers = [
            "id",
            "store_id",
            "store_name",
            "hierarchy_level_1_name",
            "hierarchy_level_2_name",
            "hierarchy_level_3_name",
            "hierarchy_level_4_name",
            "hierarchy_level_5_name",
            "departments",
            "topics",
            "keywords",
            "comment",
            "channel",
            "delivery_service",
            "sentiment",
            "sentiment_score",
            "reported_at",
            "created_at",
            "updated_at",
        ]

        # Write headers to first row
        for col_idx, header in enumerate(headers, start=1):
            ws.cell(row=1, column=col_idx, value=header)

        # Stream surveys in batches using offset
        batch_size = 100
        offset = 0
        row_num = 2  # Start from row 2 (row 1 is headers)

        while True:
            # Get surveys
            surveys = (
                filtered_query.order_by(Survey.reported_at.asc())
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not surveys:
                break
            for survey in surveys:
                csv_value = survey.to_csv()
                # Calculate sentiment based on topics
                sentiment_result = calculate_sentiment(survey)
                csv_value["sentiment"] = sentiment_result["sentiment"]
                csv_value["sentiment_score"] = sentiment_result["score"]
                
                # Write row values
                for col_idx, header in enumerate(headers, start=1):
                    value = format_excel_value(csv_value[header])
                    ws.cell(row=row_num, column=col_idx, value=value)
                row_num += 1
            offset += batch_size

        # Save workbook to BytesIO buffer
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer
    excel_buffer = generate_excel_file()
    # Await the whole excel file is generated
    url = os.getenv("ANALYZE_FEEDBACK_API_URL")
    if not url:
        raise HTTPException(status_code=500, detail="ANALYZE_FEEDBACK_API_URL is not set")
    
    url = url.rstrip('/') + "/analyze-feedback"
    print("url", url)
    payload = {'analysis_mode': 'STAT',
    'sampling_method': 'DIRECT',
    'top_n_stores': '10',
    'bottom_n_stores': '10',
    'top_n_topics': '10',
    'quote_sample_size': '5'}
    files=[
    ('file',('surveys.xlsx',excel_buffer,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))
    ]
    
    # Define headers to look like a standard request and bypass potential firewall blocks
    request_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        # Added timeout and session with trust_env=False to bypass system proxies
        session = requests.Session()
        session.trust_env = False  # This prevents requests from using system-level proxies
        response = session.post(url, data=payload, files=files, headers=request_headers, timeout=300)
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Analysis API request timed out")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to Analysis API: {str(e)}")
    
    if response.status_code != 200:
        print(f"Error from analysis API: {response.status_code}")
        print(f"Response content: {response.text}")
        raise HTTPException(status_code=response.status_code, detail=f"Analysis API error: {response.text[:500]}")

    try:
        return response.json()
    except Exception as e:
        print(f"Failed to parse JSON response: {e}")
        print(f"Raw response: {response.text}")
        raise HTTPException(status_code=500, detail=f"Analysis API returned invalid JSON: {response.text[:200]}")