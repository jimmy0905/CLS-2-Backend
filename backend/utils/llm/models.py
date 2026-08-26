from pydantic import BaseModel


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
