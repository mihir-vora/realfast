from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.db.base import Base, SessionLocal, engine
from app.db.seed import seed_if_empty

STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.db.models  # noqa: F401
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.claims import router as claims_router  # noqa: E402
from app.api.members import router as members_router  # noqa: E402

app.include_router(claims_router)
app.include_router(members_router)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/")
def serve_frontend():
    return FileResponse(str(STATIC_DIR / "index.html"))
