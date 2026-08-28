from fastapi import FastAPI

app = FastAPI(
    title="GraphOne Pipeline API",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


@app.get("/")
@app.get("/api")
@app.get("/api/index")
async def root() -> dict[str, str]:
    return {"status": "ok", "message": "GraphOne API is live"}


@app.get("/api/health")
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
