"""HTTP boundary for operational health checks."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from features.operations.service import health_service
from infrastructure.database.session import get_db

router = APIRouter()


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        return health_service(db).check()
    except Exception as error:
        raise HTTPException(status_code=500, detail="Database unavailable") from error
