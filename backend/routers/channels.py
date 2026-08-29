from fastapi import APIRouter, Depends, HTTPException
from utils.database import get_db
from models.Channel import Channel
from utils.security import get_current_user, require_admin
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(
    prefix="/channels",
    tags=["channels"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


class ChannelResponse(BaseModel):
    id: int
    name: str


@router.get("/")
async def get_channels(db: Session = Depends(get_db)):
    channels = db.query(Channel).all()
    return channels


class CreateChannelRequest(BaseModel):
    name: str


@router.post("/")
async def create_channel(
    create_channel_request: CreateChannelRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    # Check if channel already exists
    channel = (
        db.query(Channel).filter(Channel.name == create_channel_request.name).first()
    )
    if channel:
        raise HTTPException(status_code=400, detail="Channel already exists")
    channel = Channel(name=create_channel_request.name)
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


class UpdateChannelRequest(BaseModel):
    name: str


@router.put("/{channel_id}")
async def update_channel(
    channel_id: int,
    update_channel_request: UpdateChannelRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel.name = update_channel_request.name
    db.commit()
    db.refresh(channel)
    return channel


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(channel)
    db.commit()
    return {"message": f"Channel {channel.name} deleted successfully"}


@router.get("/{channel_id}")
async def get_channel(channel_id: int, db: Session = Depends(get_db)):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel
