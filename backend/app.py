from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from utils.database import check_tables_exist
from uvicorn.config import LOGGING_CONFIG
import uvicorn
from routers import (
    auth,
    surveys,
    dashboard,
    actions,
    strategy,
    userBehavoiorLogs,
    stores,
    departments,
    tasks,
    users,
    channels,
    delivery_services,
    topics,
    translator,
)
import os
from fastapi_pagination import add_pagination
from sqlalchemy.orm import Session
from sqlalchemy import text
from utils.database import get_db
from fastapi import Depends, HTTPException

app = FastAPI(
    title="CLS Connex",
    docs_url=os.getenv("FASTAPI_DOCS_URL", None),
    redoc_url=os.getenv("FASTAPI_REDOC_URL", None),
    openapi_url=os.getenv("FASTAPI_OPENAPI_URL", None),
    root_path=os.getenv("FASTAPI_ROOT_PATH", None),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add session middleware for OAuth state management
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv(
        "SESSION_SECRET_KEY", "fallback-session-secret-key-change-in-production"
    ),
)

add_pagination(app)

@app.on_event("startup")
async def startup_event():
    check_tables_exist()


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    # Check if the database is connected, by executing a simple query (list all tables in the database)
    try:
        db.execute(text("SELECT table_name FROM information_schema.tables")).all()
        return {"status": "healthy"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(auth.router)
app.include_router(surveys.router)
app.include_router(dashboard.router)
app.include_router(actions.router)
app.include_router(strategy.router)
app.include_router(stores.router)
app.include_router(departments.router)
app.include_router(userBehavoiorLogs.router)
app.include_router(tasks.router)
app.include_router(users.router)
app.include_router(channels.router)
app.include_router(delivery_services.router)
app.include_router(topics.router)
app.include_router(translator.router)


if __name__ == "__main__":
    LOGGING_CONFIG["formatters"]["default"]["fmt"] = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    LOGGING_CONFIG["formatters"]["access"]["fmt"] = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    uvicorn.run(app, host="0.0.0.0", port=8000)
