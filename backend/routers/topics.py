from re import S
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from utils.database import get_db
from models.Topic import Topic
from utils.security import get_current_user
from pydantic import BaseModel

router = APIRouter(
    prefix="/topics",
    tags=["topics"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class TopicResponse(BaseModel):
    id: int
    topic: str


@router.get("/")
async def get_topics(db: Session = Depends(get_db)):
    topics = db.query(Topic).all()
    return topics


class CreateTopicRequest(BaseModel):
    topic: str


@router.post("/")
async def create_topic(
    create_topic_request: CreateTopicRequest, db: Session = Depends(get_db)
):
    # Check if topic already exists
    topic = db.query(Topic).filter(Topic.topic == create_topic_request.topic).first()
    if topic:
        raise HTTPException(status_code=400, detail="Topic already exists")
    topic = Topic(topic=create_topic_request.topic)
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


class UpdateTopicRequest(BaseModel):
    topic: str


@router.put("/{topic_id}")
async def update_topic(
    topic_id: int,
    update_topic_request: UpdateTopicRequest,
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    topic.topic = update_topic_request.topic
    db.commit()
    db.refresh(topic)
    return topic


@router.delete("/{topic_id}")
async def delete_topic(topic_id: int, db: Session = Depends(get_db)):
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    db.delete(topic)
    db.commit()
    return {"message": f"Topic {topic.topic} deleted successfully"}


@router.get("/{topic_id}")
async def get_topic(topic_id: int, db: Session = Depends(get_db)):
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
