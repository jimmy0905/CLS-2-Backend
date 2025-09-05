from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, or_, select
from models.District import District
from models.Source import Source
from models.Survey import Survey
from models.Topic import Topic
from models.Keyword import Keyword
from models.SurveyTopics import SurveyTopics
from models.SurveyKeywords import SurveyKeywords
from models.SurveyDepartments import SurveyDepartments
from models.Store import Store
from models.Department import Department
from utils.database import get_db
from pydantic import BaseModel, Field
from typing import Literal, List, Optional
from datetime import datetime
from utils.conditionFilter import (
    build_survey_query,
    FilterRequest,
    get_filter_params,
)
from utils.llm import (
    extract_total,
)
from utils.security import get_current_user
from fastapi_pagination import Page, paginate
import logging

logger = logging.getLogger(__name__)


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


class DepartmentWithSentimentResponse(BaseModel):
    department_id: int
    name: str
    sentiment: str


class KeywordWithSentimentResponse(BaseModel):
    keyword_id: int
    keyword: str
    sentiment: str


class TopicWithSentimentResponse(BaseModel):
    topic_id: int
    topic: str
    sentiment: str


class SurveyResponse(BaseModel):
    id: int
    store: StoreResponse
    departments: List[DepartmentWithSentimentResponse]
    topics: List[TopicWithSentimentResponse]
    keywords: List[KeywordWithSentimentResponse]
    comment: str
    sentiment: str
    reported_at: datetime
    created_at: datetime
    updated_at: datetime


@router.get("")
async def get_surveys(
    filter_params: FilterRequest = Depends(get_filter_params),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[SurveyResponse]:
    filter_dict = filter_params.model_dump()
    filtered_query = build_survey_query(db.query(Survey).distinct(), filter_dict)

    # Apply ordering
    ordered_query = filtered_query.order_by(Survey.reported_at.desc())

    # Calculate total count
    total = ordered_query.count()

    # Apply pagination
    offset = (page - 1) * size
    surveys = ordered_query.offset(offset).limit(size).all()

    # Convert to response models
    survey_responses = [
        SurveyResponse.model_validate(survey.to_dict()) for survey in surveys
    ]

    # Create pagination response
    from fastapi_pagination import Params

    params = Params(page=page, size=size)

    return Page.create(items=survey_responses, total=total, params=params)


class CreateSurveyDepartmentRequest(BaseModel):
    name: str
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"


class CreateSurveyTopicRequest(BaseModel):
    topic: str
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"


class CreateSurveyKeywordRequest(BaseModel):
    keyword: str
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"


class CreateSurveyRequest(BaseModel):
    store_id: int
    departments: List[CreateSurveyDepartmentRequest]
    comment: str
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"
    topics: List[CreateSurveyTopicRequest]
    keywords: List[CreateSurveyKeywordRequest]
    reported_at: datetime = Field(default_factory=datetime.now)


@router.post("/")
async def create_survey(
    survey_request: CreateSurveyRequest,
    db: Session = Depends(get_db),
):
    try:
        # Check if store exists
        store = db.query(Store).filter(Store.id == survey_request.store_id).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        # Check if departments exist
        departments = (
            db.query(Department)
            .filter(
                Department.name.in_([dept.name for dept in survey_request.departments])
            )
            .all()
        )
        if not departments:
            raise HTTPException(status_code=404, detail="Departments not found")

        # Create survey without departments, topics, and keywords relationships
        survey = Survey(
            store_id=survey_request.store_id,
            comment=survey_request.comment,
            sentiment=survey_request.sentiment,
            reported_at=survey_request.reported_at,
        )
        db.add(survey)
        db.flush()
        # Add departments, topics, and keywords relationships
        for department in departments:
            survey_department = SurveyDepartments(
                survey_id=survey.id,
                department_id=department.id,
                sentiment=survey_request.sentiment,
            )
            db.add(survey_department)
        for request_topic in survey_request.topics:
            topic = db.query(Topic).filter(Topic.topic == request_topic.topic).first()
            # Create topic if it doesn't exist
            if not topic:
                topic = Topic(topic=request_topic.topic)
                db.add(topic)
                db.flush()
            survey_topic = SurveyTopics(
                survey_id=survey.id,
                topic_id=topic.id,
                sentiment=request_topic.sentiment,
            )
            db.add(survey_topic)
        for request_keyword in survey_request.keywords:
            keyword = (
                db.query(Keyword)
                .filter(Keyword.keyword == request_keyword.keyword)
                .first()
            )
            # Create keyword if it doesn't exist
            if not keyword:
                keyword = Keyword(keyword=request_keyword.keyword)
                db.add(keyword)
                db.flush()
            survey_keyword = SurveyKeywords(
                survey_id=survey.id,
                keyword_id=keyword.id,
                sentiment=request_keyword.sentiment,
            )
            db.add(survey_keyword)
        db.commit()
        db.refresh(survey)
        return survey.to_dict()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{survey_id}")
async def get_survey(survey_id: int, db: Session = Depends(get_db)) -> SurveyResponse:
    filter_dict = {"ids": [survey_id]}
    query = build_survey_query(db.query(Survey).distinct(), filter_dict)
    survey = query.first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    return SurveyResponse.model_validate(survey.to_dict())


class ExtractRequest(BaseModel):
    comment: str


class ExtractedTopicResponse(BaseModel):
    text: str
    sentiment: str


class ExtractedDepartmentResponse(BaseModel):
    text: str
    sentiment: str


class ExtractedKeywordResponse(BaseModel):
    text: str
    sentiment: str


class TotalResponse(BaseModel):
    topics: list[ExtractedTopicResponse]
    departments: list[ExtractedDepartmentResponse]
    keywords: list[ExtractedKeywordResponse]
    overall_sentiment: str
    cannot_classified: bool


@router.post("/extract-total")
async def extract_total_route(
    request: ExtractRequest,
) -> tuple[TotalResponse, dict]:
    total, usage = await extract_total(request.comment)
    print(total)
    return total, usage
