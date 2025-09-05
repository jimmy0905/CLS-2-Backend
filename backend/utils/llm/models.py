from pydantic import BaseModel


class EmailResponse(BaseModel):
    subject_line: str
    email_body: str


class Topic(BaseModel):
    text: str
    sentiment: str


class Department(BaseModel):
    text: str
    sentiment: str

class Keywords(BaseModel):
    text: str
    sentiment: str

class TotalResponse(BaseModel):
    topics: list[Topic]
    keywords: list[Keywords]
    departments: list[Department]
    overall_sentiment: str
    cannot_classified: bool


class Action(BaseModel):
    type: str
    priority: str
    to: list[str]
    cc: list[str]
    name: str
    des: str
    prompt_for_subject_line: str
    prompt_for_email_body: str


class ActionsResponse(BaseModel):
    summary: str
    impact_analysis_summary: str
    actions: list[Action]


class EmailData(BaseModel):
    summary: str
    action: Action
    survey_data: list[dict]
