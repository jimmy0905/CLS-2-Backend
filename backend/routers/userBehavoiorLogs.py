from fastapi import APIRouter, Depends, HTTPException
from models.db_config import get_db
from models.User import User
from utils.security import get_current_user
from sqlalchemy.orm import Session
from models.Action import Action
from models.GeneratedEmail import GeneratedEmail
from models.EmailRecord import EmailRecord

router = APIRouter(
    prefix="/user-behavior-logs",
    tags=["user-behavior-logs"],
    dependencies=[Depends(get_db), Depends(get_current_user)],
)


@router.get("/actions")
async def get_actions(db: Session = Depends(get_db)):
    actions = db.query(Action).all()
    return actions


@router.get("/actions/{action_id}")
async def get_action(action_id: int, db: Session = Depends(get_db)):
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


@router.get("/actions/user/{user_id}")
async def get_actions_by_user(user_id: str, db: Session = Depends(get_db)):
    actions = db.query(Action).filter(Action.user_id == user_id).all()
    return actions


@router.get("/generated-emails")
async def get_emails(db: Session = Depends(get_db)):
    emails = db.query(GeneratedEmail).all()
    return emails


@router.get("/generated-emails/{email_id}")
async def get_email(email_id: int, db: Session = Depends(get_db)):
    email = db.query(GeneratedEmail).filter(GeneratedEmail.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email

@router.get("/generated-emails/user/{user_id}")
async def get_emails_by_user(user_id: str, db: Session = Depends(get_db)):
    emails = db.query(GeneratedEmail).filter(GeneratedEmail.user_id == user_id).all()
    return emails

@router.get("/email-records")
async def get_email_records(db: Session = Depends(get_db)):
    email_records = db.query(EmailRecord).all()
    return email_records

@router.get("/email-records/{email_record_id}")
async def get_email_record(email_record_id: int, db: Session = Depends(get_db)):
    email_record = db.query(EmailRecord).filter(EmailRecord.id == email_record_id).first()
    if not email_record:
        raise HTTPException(status_code=404, detail="Email record not found")
    return email_record

@router.get("/email-records/user/{user_id}")
async def get_email_records_by_user(user_id: str, db: Session = Depends(get_db)):
    email_records = db.query(EmailRecord).filter(EmailRecord.user_id == user_id).all()
    return email_records
