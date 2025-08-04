from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, or_
from models.District import District
from models.Source import Source
from models.Survey import Survey
from models.Topic import Topic
from models.Keyword import Keyword
from models.SurveyTopics import SurveyTopics
from models.SurveyKeywords import SurveyKeywords
from models.Store import Store
from models.Department import Department
from models.db_config import get_db
from pydantic import BaseModel, Field
from typing import Literal, List, Optional
from datetime import datetime
from utils.conditionFilter import (
    build_survey_query,
)
from utils.llm import (
    extract_keywords,
    extract_topics,
    extract_department,
    extract_sentiment,
)
from utils.security import get_current_user


router = APIRouter(
    prefix="/surveys",
    tags=["surveys"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class DistrictResponse(BaseModel):
    id: int
    name: str


class RegionResponse(BaseModel):
    id: int
    name: str


class SourceResponse(BaseModel):
    id: int
    name: str


class StoreResponse(BaseModel):
    id: int
    name: str
    district: DistrictResponse
    source: SourceResponse
    region: RegionResponse

class DepartmentResponse(BaseModel):
    id: int
    name: str


class SurveyResponse(BaseModel):
    id: int
    store: StoreResponse
    department: DepartmentResponse
    comment: str
    sentiment: str
    cls_score: Optional[float] = None
    wish_list: Optional[str] = None
    reported_at: datetime
    created_at: datetime
    updated_at: datetime
    topics: List[str]
    keywords: List[str]


class FilterRequest(BaseModel):
    store_ids: List[int] = []
    store_names: List[str] = []
    department_ids: List[int] = []
    department_names: List[str] = []
    district_ids: List[int] = []
    district_names: List[str] = []
    region_ids: List[int] = []
    region_names: List[str] = []
    source_ids: List[int] = []
    source_names: List[str] = []
    topics: List[str] = []
    from_date: Optional[str] = ""
    to_date: Optional[str] = ""
    sentiments: List[str] = []


def get_filter_params(
    store_ids: List[int] = Query(
        default=[],
        description="The store ids to filter by, separated by |",
    ),
    store_names: List[str] = Query(
        default=[],
        description="The store names to filter by",
    ),
    department_ids: List[int] = Query(
        default=[],
        description="The department ids to filter by",
    ),
    department_names: List[str] = Query(
        default=[],
        description="The department names to filter by",
    ),
    district_ids: List[int] = Query(
        default=[],
        description="The district ids to filter by",
    ),
    district_names: List[str] = Query(
        default=[],
        description="The district names to filter by",
    ),
    region_ids: List[int] = Query(
        default=[],
        description="The region ids to filter by",
    ),
    region_names: List[str] = Query(
        default=[],
        description="The region names to filter by",
    ),
    source_ids: List[int] = Query(
        default=[],
        description="The source ids to filter by",
    ),
    source_names: List[str] = Query(
        default=[],
        description="The source names to filter by",
    ),
    topics: List[str] = Query(
        default=[],
        description="The topics to filter by",
    ),
    from_date: str = Query(
        default="",
        description="The start date to filter by, in the format YYYY-MM-DD",
    ),
    to_date: str = Query(
        default="",
        description="The end date to filter by, in the format YYYY-MM-DD",
    ),
    sentiments: List[str] = Query(
        default=[],
        description="The sentiments to filter by",
    ),
) -> FilterRequest:
    # store_ids and store_names cannot be used together
    if store_ids and store_names:
        raise HTTPException(
            status_code=400,
            detail="store_ids and store_names cannot be used together",
        )
    # department_ids and department_names cannot be used together
    if department_ids and department_names:
        raise HTTPException(
            status_code=400,
            detail="department_ids and department_names cannot be used together",
        )
    # district_ids and district_names cannot be used together
    if district_ids and district_names:
        raise HTTPException(
            status_code=400,
            detail="district_ids and district_names cannot be used together",
        )
    # source_ids and source_names cannot be used together
    if source_ids and source_names:
        raise HTTPException(
            status_code=400,
            detail="source_ids and source_names cannot be used together",
        )

    return FilterRequest(
        store_ids=store_ids,
        store_names=store_names,
        department_ids=department_ids,
        department_names=department_names,
        district_ids=district_ids,
        district_names=district_names,
        source_ids=source_ids,
        source_names=source_names,
        topics=topics,
        from_date=from_date,
        to_date=to_date,
        sentiments=sentiments,
    )


@router.get("")
async def get_surveys(
    filter_params: FilterRequest = Depends(get_filter_params),
    db: Session = Depends(get_db),
) -> List[SurveyResponse]:
    filter_dict = filter_params.model_dump()
    filtered_query = build_survey_query(db.query(Survey).distinct(), filter_dict)

    # Execute the query
    surveys = filtered_query.all()
    return [SurveyResponse.model_validate(survey.to_dict()) for survey in surveys]


class CreateSurveyRequest(BaseModel):
    store_id: int
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    comment: str
    sentiment: Literal["Positive", "Negative", "Neutral"]
    cls_score: Optional[float] = None
    wish_list: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    reported_at: datetime = Field(default_factory=datetime.now)


@router.post("/")
async def create_survey(
    survey_request: CreateSurveyRequest,
    db: Session = Depends(get_db),
):
    try:
        # department_id and department_name cannot be provided together
        if (
            survey_request.department_id is not None
            and survey_request.department_name is not None
        ):
            raise HTTPException(
                status_code=400,
                detail="Department id and name cannot be provided together",
            )
        # if department_id is not provided, check if department_name exists
        if (
            survey_request.department_id is None
            and survey_request.department_name is not None
        ):
            department = (
                db.query(Department)
                .filter(Department.name == survey_request.department_name)
                .first()
            )
            if not department:
                raise HTTPException(status_code=404, detail="Department not found")
            survey_request.department_id = department.id
        # Check if store exists
        store = db.query(Store).filter(Store.id == survey_request.store_id).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        # Create the survey first without relationships
        survey = Survey(
            store_id=survey_request.store_id,
            department_id=survey_request.department_id,
            comment=survey_request.comment,
            sentiment=survey_request.sentiment,
            reported_at=survey_request.reported_at,
            cls_score=survey_request.cls_score,
            wish_list=survey_request.wish_list,
        )
        db.add(survey)
        db.flush()

        new_topics = []
        topic_associations = []

        for topic_str in survey_request.topics:
            existing_topic = db.query(Topic).filter(Topic.topic == topic_str).first()
            if existing_topic:
                topic = existing_topic
            else:
                topic = Topic(topic=topic_str)
                new_topics.append(topic)
                db.add(topic)

        if new_topics:
            db.flush()

        # Create all topic associations
        for topic_str in survey_request.topics:
            existing_topic = db.query(Topic).filter(Topic.topic == topic_str).first()
            topic = (
                existing_topic
                if existing_topic
                else next(t for t in new_topics if t.topic == topic_str)
            )
            topic_associations.append(
                SurveyTopics(survey_id=survey.id, topic_id=topic.id)
            )

        if topic_associations:
            db.bulk_save_objects(topic_associations)

        new_keywords = []
        keyword_associations = []

        for keyword_str in survey_request.keywords:
            existing_keyword = (
                db.query(Keyword).filter(Keyword.keyword == keyword_str).first()
            )
            if existing_keyword:
                keyword = existing_keyword
            else:
                keyword = Keyword(keyword=keyword_str)
                new_keywords.append(keyword)
                db.add(keyword)

        if new_keywords:
            db.flush()

        # Create all keyword associations
        for keyword_str in survey_request.keywords:
            existing_keyword = (
                db.query(Keyword).filter(Keyword.keyword == keyword_str).first()
            )
            keyword = (
                existing_keyword
                if existing_keyword
                else next(k for k in new_keywords if k.keyword == keyword_str)
            )
            keyword_associations.append(
                SurveyKeywords(survey_id=survey.id, keyword_id=keyword.id)
            )

        if keyword_associations:
            db.bulk_save_objects(keyword_associations)

        db.commit()
        return {
            "id": survey.id,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{survey_id}")
async def get_survey(survey_id: int, db: Session = Depends(get_db)) -> SurveyResponse:
    survey = (
        db.query(Survey)
        .options(
            joinedload(Survey.survey_topics).joinedload(SurveyTopics.topic),
            joinedload(Survey.survey_keywords).joinedload(SurveyKeywords.keyword),
            joinedload(Survey.store),
            joinedload(Survey.department),
            joinedload(Survey.district),
            joinedload(Survey.source),
        )
        .filter(Survey.id == survey_id)
        .first()
    )
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    return SurveyResponse.model_validate(survey.to_dict())


class ExtractRequest(BaseModel):
    comment: str


@router.post("/extract-keywords")
async def extract_keywords_route(
    request: ExtractRequest,
) -> List[str]:
    keywords = await extract_keywords(request.comment)
    return keywords


@router.post("/extract-topics")
async def extract_topics_route(
    request: ExtractRequest,
) -> List[str]:
    topics = await extract_topics(request.comment)
    return topics


@router.post("/extract-department")
async def extract_department_route(
    request: ExtractRequest,
) -> str:
    department = await extract_department(request.comment)
    return department


@router.post("/extract-sentiment")
async def extract_sentiment_route(
    request: ExtractRequest,
) -> List[str]:
    sentiment = await extract_sentiment(request.comment)
    return [sentiment]
