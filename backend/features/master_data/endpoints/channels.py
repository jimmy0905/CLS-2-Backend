from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from features.master_data.dto import (
    ChannelResponse,
    CreateChannelRequest,
    UpdateChannelRequest,
)
from features.master_data.service import channel_service
from infrastructure.database.session import get_db
from features.identity.service.security import get_current_actor, require_admin

router = APIRouter(
    prefix="/channels",
    tags=["channels"],
    dependencies=[Depends(get_db), Depends(get_current_actor)],
)


@router.get("/")
async def get_channels(db: Session = Depends(get_db)):
    return channel_service(db).list()


@router.post("/")
async def create_channel(
    create_channel_request: CreateChannelRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return channel_service(db).create(create_channel_request.name)


@router.put("/{channel_id}")
async def update_channel(
    channel_id: int,
    update_channel_request: UpdateChannelRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return channel_service(db).update(channel_id, update_channel_request.name)


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    return {"message": channel_service(db).delete(channel_id)}


@router.get("/{channel_id}")
async def get_channel(channel_id: int, db: Session = Depends(get_db)):
    return channel_service(db).get(channel_id)
