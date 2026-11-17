from fastapi import FastAPI
from app.api.auth import router as auth_router
from app.api.contests import router as contests_router
from app.api.problems import router as problems_router
from app.api.submissions import router as submissions_router

app = FastAPI(
    title="Shodh Contest Platform",
    description="Backend API for the Shodh coding contest platform",
    version="1.0.0",
)

app.include_router(auth_router)
app.include_router(contests_router)
app.include_router(problems_router)
app.include_router(submissions_router)

@app.get("/")
def root():
    return {"message": "Shodh Contest Platform API", "status": "running"}

@app.get("/health")
def health():
    return {"status": "healthy"}
