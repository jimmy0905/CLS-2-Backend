from fastapi import APIRouter, Depends, HTTPException
from models.Survey import Survey
from utils.conditionFilter import build_survey_query
from utils.database import get_db
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, Field
from typing import Optional
from utils.llm.models import (
    Action,
    EmailData,
    EmailResponse,
)
from utils.llm.generate_actions import generate_actions
from utils.llm.generate_email import generate_email
from utils.smtp import send_email as send_email_utils
from utils.security import get_current_user
from utils.logger import logger
from typing import List
from models.User import User
from models.Action import Action as ActionDatabaseModel
from models.GeneratedEmail import GeneratedEmail
from models.EmailRecord import EmailRecord
from sqlalchemy import func
import asyncio

router = APIRouter(
    prefix="/actions",
    tags=["actions"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class ActionFilterRequest(BaseModel):
    store_keys: List[int] = []
    store_names: List[str] = []
    channel_ids: List[int] = []
    channel_names: List[str] = []
    delivery_service_ids: List[int] = []
    delivery_service_names: List[str] = []
    department_ids: List[int] = []
    department_names: List[str] = []
    district_ids: List[int] = []
    district_names: List[str] = []
    region_ids: List[int] = []
    region_names: List[str] = []
    source_ids: List[int] = []
    source_names: List[str] = []
    topics: List[str] = []
    keywords: List[str] = []
    from_date: Optional[str] = ""
    to_date: Optional[str] = ""
    sentiments: List[str] = []
    topic_sentiments: List[str] = []
    min_topic_sentiment_score: Optional[float] = None
    max_topic_sentiment_score: Optional[float] = None
    min_cls: Optional[float] = None
    max_cls: Optional[float] = None


class GetActionsResponse(BaseModel):
    id: int
    summary: str
    impact_analysis_summary: str
    actions: list[Action]
    survey_data: list[dict]


@router.post("")
async def get_actions(
    action_filter_request: ActionFilterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GetActionsResponse:
    # store_keys and store_names cannot be used together
    if action_filter_request.store_keys and action_filter_request.store_names:
        raise HTTPException(
            status_code=400,
            detail="store_keys and store_names cannot be used together",
        )
    # department_ids and department_names cannot be used together
    if action_filter_request.department_ids and action_filter_request.department_names:
        raise HTTPException(
            status_code=400,
            detail="department_ids and department_names cannot be used together",
        )
    # district_ids and district_names cannot be used together
    if action_filter_request.district_ids and action_filter_request.district_names:
        raise HTTPException(
            status_code=400,
            detail="district_ids and district_names cannot be used together",
        )
    # region_ids and region_names cannot be used together
    if action_filter_request.region_ids and action_filter_request.region_names:
        raise HTTPException(
            status_code=400,
            detail="region_ids and region_names cannot be used together",
        )
    # source_ids and source_names cannot be used together
    if action_filter_request.source_ids and action_filter_request.source_names:
        raise HTTPException(
            status_code=400,
            detail="source_ids and source_names cannot be used together",
        )
    # available topic_sentiments are POSITIVE, NEGATIVE, NEUTRAL, MIXED
    valid_topic_sentiments = ["POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"]
    if action_filter_request.topic_sentiments:
        invalid_topic_sentiments = [
            sentiment
            for sentiment in action_filter_request.topic_sentiments
            if sentiment not in valid_topic_sentiments
        ]
        if invalid_topic_sentiments:
            raise HTTPException(
                status_code=400,
                detail=f"topic_sentiments must be one of {', '.join(valid_topic_sentiments)}. Invalid values: {', '.join(invalid_topic_sentiments)}",
            )
    # available sentiments are POSITIVE, NEGATIVE, NEUTRAL
    valid_sentiments = ["POSITIVE", "NEGATIVE", "NEUTRAL"]
    if action_filter_request.sentiments:
        invalid_sentiments = [
            sentiment
            for sentiment in action_filter_request.sentiments
            if sentiment not in valid_sentiments
        ]
        if invalid_sentiments:
            raise HTTPException(
                status_code=400,
                detail=f"sentiments must be one of {', '.join(valid_sentiments)}. Invalid values: {', '.join(invalid_sentiments)}",
            )
    filter_dict = action_filter_request.model_dump()
    
    # First get distinct survey IDs that match the filters
    # Include comment in select for ORDER BY compatibility with DISTINCT
    id_query = build_survey_query(db.query(Survey.id, Survey.comment).distinct(), filter_dict)
    id_query = id_query.order_by(func.length(Survey.comment).desc()).limit(500)
    survey_ids = [row[0] for row in id_query.all()]
    
    # Execute the query to get full survey objects
    surveys = (
        db.query(Survey)
        .filter(Survey.id.in_(survey_ids))
        .options(
            joinedload(Survey.store),
            joinedload(Survey.survey_topics),
            joinedload(Survey.survey_keywords),
            joinedload(Survey.survey_departments),
            joinedload(Survey.channel),
            joinedload(Survey.delivery_service)
        )
        .order_by(func.length(Survey.comment).desc())
        .all()
    ) if survey_ids else []

    # Check the length of the surveys
    if len(surveys) == 0:
        raise HTTPException(status_code=404, detail="No surveys found")
    logger.info(
        "Generating recommended actions",
        extra={"event": "actions.generation.started", "survey_count": len(surveys)},
    )
    actions, _ = await generate_actions(surveys)
    logger.info(
        "Generated recommended actions",
        extra={"event": "actions.generation.completed", "survey_count": len(surveys)},
    )
    action = ActionDatabaseModel(
        user_id=current_user.id,
        summary=actions.summary,
        actions_items=[action.model_dump(mode="json") for action in actions.actions],
        survey_data=[survey.to_dict() for survey in surveys],
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    logger.info(
        "Persisted recommended actions",
        extra={"event": "actions.persisted", "action_id": action.id},
    )
    return GetActionsResponse(
        id=action.id,
        summary=actions.summary,
        impact_analysis_summary=actions.impact_analysis_summary,
        actions=actions.actions,
        # survey_data=[{"id": survey.id} for survey in surveys],
        survey_data=[],
    )


class EmailRequest(BaseModel):
    summary: str
    action: Action
    action_id: int


class EmailResponse(BaseModel):
    subject_line: str = Field(default="")
    email_body: str = Field(default="")


@router.post("/generate-email")
async def generate_email_route(
    email_request: EmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailResponse:

    action = (
        db.query(ActionDatabaseModel)
        .filter(ActionDatabaseModel.id == email_request.action_id)
        .first()
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    # Convert EmailRequest to EmailData format
    email_data = EmailData(
        summary=email_request.summary,
        action=email_request.action,
        survey_data=[id for id in action.survey_data],
    )

    llm_response, _ = await generate_email(email_data)
    generated_email = GeneratedEmail(
        user_id=current_user.id,
        input_data=email_data.model_dump(mode="json"),
        subject_line=llm_response.subject_line,
        email_body=llm_response.email_body,
    )
    db.add(generated_email)
    db.commit()

    # Convert LLM response to our response format
    return EmailResponse(
        subject_line=llm_response.subject_line, email_body=llm_response.email_body
    )


class SendEmailRequest(BaseModel):
    subject_line: str
    email_body: str
    to: list[str]
    cc: Optional[list[str]] = None


@router.post("/send-email")
async def send_email(
    send_email_request: SendEmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await send_email_utils(
        send_email_request.subject_line,
        send_email_request.email_body,
        send_email_request.to,
        send_email_request.cc or [],
    )

    email_record = EmailRecord(
        user_id=current_user.id,
        subject_line=send_email_request.subject_line,
        email_body=send_email_request.email_body,
        to=send_email_request.to,
        cc=send_email_request.cc or [],
    )
    db.add(email_record)
    db.commit()
    return {"message": "Email sent successfully"}
