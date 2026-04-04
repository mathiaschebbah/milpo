from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import posts, annotations

app = FastAPI(title="HILPO", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(posts.router)
app.include_router(annotations.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
