from fastapi import APIRouter, Depends, HTTPException
from models.Survey import Survey
from utils.conditionFilter import build_optimized_query
from utils.database import get_db
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from utils.llm import (
    Action,
    generate_actions,
    generate_email as generate_email_llm,
    EmailData,
)
from datetime import datetime
from utils.smtp import send_email as send_email_utils
from utils.security import get_current_user
from typing import List
from models.User import User
from models.Action import Action as ActionDatabaseModel
from models.GeneratedEmail import GeneratedEmail
from models.EmailRecord import EmailRecord

router = APIRouter(
    prefix="/actions",
    tags=["actions"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class ActionFilterRequest(BaseModel):
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
    keywords: List[str] = []
    from_date: Optional[str] = ""
    to_date: Optional[str] = ""
    sentiments: List[str] = []


class DistrictResponse(BaseModel):
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


class DepartmentResponse(BaseModel):
    id: int
    name: str


class SurveyResponse(BaseModel):
    id: int
    store: StoreResponse
    department: DepartmentResponse
    comment: str
    sentiment: str
    reported_at: datetime
    created_at: datetime
    updated_at: datetime
    topics: List[str]
    keywords: List[str]


class GetActionsResponse(BaseModel):
    summary: str
    impact_analysis_summary: str
    actions: list[Action]
    survey_data: list[SurveyResponse]


@router.post("")
async def get_actions(
    action_filter_request: ActionFilterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GetActionsResponse:
    # store_ids and store_names cannot be used together
    if action_filter_request.store_ids and action_filter_request.store_names:
        raise HTTPException(
            status_code=400,
            detail="store_ids and store_names cannot be used together",
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
    filter_dict = action_filter_request.model_dump()
    filtered_query, _ = build_optimized_query(db, filter_dict)

    # Execute the query
    surveys = filtered_query.all()

    # Check the length of the surveys
    if len(surveys) == 0:
        raise HTTPException(status_code=404, detail="No surveys found")

    LIMIT = 100
    # Check if the length of the surveys is greater than 10
    if len(surveys) > LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Too many surveys found, please filter the data, there are {len(surveys)} surveys found. Max is {LIMIT}.",
        )
    actions, _ = await generate_actions(surveys)
    survey_data = [
        SurveyResponse.model_validate(survey.to_dict()) for survey in surveys
    ]
    action = ActionDatabaseModel(
        user_id=current_user.id,
        summary=actions.summary,
        actions_items=[action.model_dump(mode="json") for action in actions.actions],
        survey_data=[survey.model_dump(mode="json") for survey in survey_data],
    )
    db.add(action)
    db.commit()
    return GetActionsResponse(
        summary=actions.summary,
        impact_analysis_summary=actions.impact_analysis_summary,
        actions=actions.actions,
        survey_data=survey_data,
    )


class EmailRequest(BaseModel):
    summary: str
    action: Action
    survey_data: list[SurveyResponse]


class EmailResponse(BaseModel):
    subject_line: str = Field(default="")
    email_body: str = Field(default="")


@router.post("/generate-email")
async def generate_email(
    email_request: EmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailResponse:
    # Convert EmailRequest to EmailData format
    survey_data_dicts = [
        survey.model_dump(mode="json") for survey in email_request.survey_data
    ]
    email_data = EmailData(
        summary=email_request.summary,
        action=email_request.action,
        survey_data=survey_data_dicts,
    )

    llm_response, _ = await generate_email_llm(email_data)
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
