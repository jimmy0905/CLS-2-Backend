from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import check_tables_exist
import uvicorn
from routers import (
    auth,
    surveys,
    dashboard,
    actions,
    strategy,
    userBehavoiorLogs,
    districts,
    stores,
    sources,
    departments,
    regions,
    tasks,
    users,
)
import os
from config import PATH_TO_UPLOAD_FOLDER

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


@app.on_event("startup")
async def startup_event():
    check_tables_exist()


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


app.include_router(auth.router)
app.include_router(surveys.router)
app.include_router(dashboard.router)
app.include_router(actions.router)
app.include_router(strategy.router)
app.include_router(districts.router)
app.include_router(stores.router)
app.include_router(sources.router)
app.include_router(departments.router)
app.include_router(userBehavoiorLogs.router)
app.include_router(regions.router)
app.include_router(tasks.router)
app.include_router(users.router)





if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
