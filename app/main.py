from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.base import Base, SessionLocal, engine
from app.db.seed import seed_if_empty


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.db.models  # noqa: F401  — ensure models are registered before create_all
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Claims Processing System",
    description="Insurance claims adjudication and lifecycle management",
    version="0.1.0",
    lifespan=lifespan,
)

from app.api.claims import router as claims_router  # noqa: E402

app.include_router(claims_router)


@app.get("/health")
def health_check():
    return {"status": "healthy"}
