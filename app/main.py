from fastapi import FastAPI

app = FastAPI(
    title="Claims Processing System",
    description="Insurance claims adjudication and lifecycle management",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {"status": "healthy"}
