from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from core.time import as_utc, utc_now
from features.feedback.filtering import build_survey_query
from features.identity.service.security import get_current_actor, require_admin
from infrastructure.database.dbo.Channel import Channel
from infrastructure.database.dbo.DeliveryService import DeliveryService
from infrastructure.database.dbo.Department import Department
from infrastructure.database.dbo.Keyword import Keyword
from infrastructure.database.dbo.Store import Store
from infrastructure.database.dbo.Survey import Survey
from infrastructure.database.dbo.SurveyDepartments import SurveyDepartments
from infrastructure.database.dbo.SurveyKeywords import SurveyKeywords
from infrastructure.database.dbo.SurveyTopics import SurveyTopics
from infrastructure.database.dbo.Topic import Topic
from infrastructure.database.session import get_db

router = APIRouter(
    prefix="/surveys",
    tags=["surveys"],
    dependencies=[Depends(get_db), Depends(get_current_actor)],
)


class StoreResponse(BaseModel):
    store_key: int
    store_name_english: Optional[str] = None
    store_name_local: Optional[str] = None
    bu_key: Optional[str] = None
    area_manager: Optional[str] = None
    store_format: Optional[str] = None
    store_type: Optional[str] = None
    operations_controller: Optional[str] = None
    regional_manager: Optional[str] = None
    px: Optional[str] = None
    csr: Optional[str] = None
    dr: Optional[str] = None
    mag_type: Optional[str] = None
    cf_grouping: Optional[str] = None
    store_brand: Optional[str] = None
    competitor: Optional[str] = None
    region: Optional[str] = None
    area: Optional[str] = None
    province: Optional[str] = None
    territory: Optional[str] = None
    toh: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    operations_manager: Optional[str] = None
    district_manager: Optional[str] = None
    sic: Optional[str] = None
    soc: Optional[str] = None
    tech_life_type: Optional[str] = None
    operation_manager_tl: Optional[str] = None
    region_manager_tl: Optional[str] = None
    relocation: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    store_open_date: Optional[str] = None
    store_close_date: Optional[str] = None
    is_closed: bool


class ChannelResponse(BaseModel):
    id: int
    name: str


class DeliveryServiceResponse(BaseModel):
    id: int
    name: str


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
    channel: Optional[ChannelResponse]
    delivery_service: Optional[DeliveryServiceResponse]
    departments: List[DepartmentWithSentimentResponse]
    topics: List[TopicWithSentimentResponse]
    keywords: List[KeywordWithSentimentResponse]
    comment: str
    sentiment: str
    topic_sentiment: str
    topic_sentiment_score: float
    cls: Optional[float] = None
    reported_at: str
    created_at: str
    updated_at: str


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
    store_key: int
    channel: Optional[str] = None
    delivery_service: Optional[str] = None
    departments: List[CreateSurveyDepartmentRequest]
    comment: str
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"
    topics: List[CreateSurveyTopicRequest]
    keywords: List[CreateSurveyKeywordRequest]
    reported_at: datetime = Field(default_factory=utc_now)
    cls: Optional[float] = None


@router.post("/")
async def create_survey(
    survey_request: CreateSurveyRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):

    # Check if store exists
    store = db.query(Store).filter(Store.store_key == survey_request.store_key).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    # Check if departments exist
    departments = (
        db.query(Department)
        .filter(Department.name.in_([dept.name for dept in survey_request.departments]))
        .all()
    )
    if not departments:
        raise HTTPException(status_code=404, detail="Departments not found")
    # Check if topics exist
    topics = (
        db.query(Topic)
        .filter(Topic.topic.in_([topic.topic for topic in survey_request.topics]))
        .all()
    )
    if not topics:
        raise HTTPException(status_code=404, detail="Topics not found")
    # Initialize channel and delivery_service to None
    channel = None
    delivery_service = None

    # If channel is provided, check if channel exists
    if survey_request.channel:
        channel = (
            db.query(Channel).filter(Channel.name == survey_request.channel).first()
        )
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
    # If delivery service is provided, check if delivery service exists
    if survey_request.delivery_service:
        delivery_service = (
            db.query(DeliveryService)
            .filter(DeliveryService.name == survey_request.delivery_service)
            .first()
        )
        if not delivery_service:
            raise HTTPException(status_code=404, detail="Delivery service not found")
    try:
        # Create survey without departments, topics, and keywords relationships
        survey = Survey(
            store_key=survey_request.store_key,
            comment=survey_request.comment,
            sentiment=survey_request.sentiment,
            reported_at=as_utc(survey_request.reported_at),
            cls=survey_request.cls,
            channel_id=channel.id if channel else None,
            delivery_service_id=delivery_service.id if delivery_service else None,
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

class UpdateSurveyTopicRequest(BaseModel):
    topic: str
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"


class UpdateSurveyKeywordRequest(BaseModel):
    keyword: str
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"


class UpdateSurveyDepartmentRequest(BaseModel):
    name: str
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"


class UpdateSurveyRequest(BaseModel):
    store_key: Optional[int] = None
    channel: Optional[str] = None
    delivery_service: Optional[str] = None
    departments: Optional[List[UpdateSurveyDepartmentRequest]] = None
    comment: Optional[str] = None
    sentiment: Optional[Literal["positive", "negative", "neutral"]] = None
    topics: Optional[List[UpdateSurveyTopicRequest]] = None
    keywords: Optional[List[UpdateSurveyKeywordRequest]] = None
    reported_at: Optional[datetime] = None
    cls: Optional[float] = None


@router.put("/{survey_id}")
async def update_survey(
    survey_id: int,
    survey_request: UpdateSurveyRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
) -> SurveyResponse:
    try:
        filter_dict = {"ids": [survey_id]}
        query = build_survey_query(db.query(Survey), filter_dict)
        query = query.options(
            joinedload(Survey.store),
            joinedload(Survey.survey_topics),
            joinedload(Survey.survey_keywords),
            joinedload(Survey.survey_departments),
            joinedload(Survey.channel),
            joinedload(Survey.delivery_service)
        )
        survey = query.first()
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")
        if survey_request.store_key:
            survey.store_key = survey_request.store_key
        if survey_request.channel:
            survey.channel_id = survey_request.channel
        if survey_request.delivery_service:
            survey.delivery_service_id = survey_request.delivery_service
        if survey_request.departments:
            for department in survey_request.departments:
                survey_department = (
                    db.query(SurveyDepartments)
                    .filter(
                        SurveyDepartments.survey_id == survey.id,
                        SurveyDepartments.department_id == department.name,
                    )
                    .first()
                )
                if not survey_department:
                    survey_department = SurveyDepartments(
                        survey_id=survey.id,
                        department_id=department.name,
                        sentiment=department.sentiment,
                    )
                    db.add(survey_department)
                else:
                    survey_department.sentiment = department.sentiment
        if survey_request.comment:
            survey.comment = survey_request.comment
        if survey_request.sentiment:
            survey.sentiment = survey_request.sentiment
        if survey_request.topics:
            for topic in survey_request.topics:
                survey_topic = (
                    db.query(SurveyTopics)
                    .filter(
                        SurveyTopics.survey_id == survey.id,
                        SurveyTopics.topic_id == topic.topic,
                    )
                    .first()
                )
                if not survey_topic:
                    survey_topic = SurveyTopics(
                        survey_id=survey.id,
                        topic_id=topic.topic,
                        sentiment=topic.sentiment,
                    )
                    db.add(survey_topic)
                else:
                    survey_topic.sentiment = topic.sentiment
        if survey_request.keywords:
            for keyword in survey_request.keywords:
                survey_keyword = (
                    db.query(SurveyKeywords)
                    .filter(
                        SurveyKeywords.survey_id == survey.id,
                        SurveyKeywords.keyword_id == keyword.keyword,
                    )
                    .first()
                )
                if not survey_keyword:
                    survey_keyword = SurveyKeywords(
                        survey_id=survey.id,
                        keyword_id=keyword.keyword,
                        sentiment=keyword.sentiment,
                    )
                    db.add(survey_keyword)
                else:
                    survey_keyword.sentiment = keyword.sentiment
        if survey_request.reported_at:
            survey.reported_at = as_utc(survey_request.reported_at)
        if survey_request.cls is not None:
            survey.cls = survey_request.cls
        db.commit()
        db.refresh(survey)
        return SurveyResponse.model_validate(survey.to_dict())
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{survey_id}")
async def delete_survey(
    survey_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
) -> SurveyResponse:
    try:
        filter_dict = {"ids": [survey_id]}
        query = build_survey_query(db.query(Survey), filter_dict)
        query = query.options(
            joinedload(Survey.store),
            joinedload(Survey.survey_topics),
            joinedload(Survey.survey_keywords),
            joinedload(Survey.survey_departments),
            joinedload(Survey.channel),
            joinedload(Survey.delivery_service)
        )
        survey = query.first()
        if not survey:
            raise HTTPException(status_code=404, detail="Survey not found")
        survey.is_deleted = True
        db.commit()
        db.refresh(survey)
        return SurveyResponse.model_validate(survey.to_dict())
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
