from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from features.master_data.dto import CreateTopicRequest, UpdateTopicRequest
from features.master_data.service import topic_service
from infrastructure.database.session import get_db
from features.identity.service.security import get_current_user, require_admin

router = APIRouter(
    prefix="/topics",
    tags=["topics"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


@router.get("/")
async def get_topics(db: Session = Depends(get_db)):
    return topic_service(db).list()


@router.post("/")
async def create_topic(
    create_topic_request: CreateTopicRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return topic_service(db).create(create_topic_request.topic)


@router.put("/{topic_id}")
async def update_topic(
    topic_id: int,
    update_topic_request: UpdateTopicRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return topic_service(db).update(topic_id, update_topic_request.topic)


@router.delete("/{topic_id}")
async def delete_topic(
    topic_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return {"message": topic_service(db).delete(topic_id)}


@router.get("/{topic_id}")
async def get_topic(topic_id: int, db: Session = Depends(get_db)):
    return topic_service(db).get(topic_id)
