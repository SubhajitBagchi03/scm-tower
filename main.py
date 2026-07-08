from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import os

load_dotenv()

from database import init_db, reset_db
from api import upload, rag, inventory, agent
from api import csv_upload

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("[INFO] Database tables initialized")
    yield

app = FastAPI(
    title="Supply Chain Agentic AI Control Tower",
    description="Enterprise-grade multi-agent system for SCM intelligence",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://scm-deployedd.vercel.app",  # replace with actual Vercel URL
        "https://*.vercel.app",                 # covers all preview deployments too
        "https://*.onrender.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# PDF RAG upload:  POST /upload/pdf
# CSV preview:     POST /upload/preview
# CSV commit:      POST /upload/commit
# CSV file list:   GET  /upload/files
# CSV conflicts:   GET  /upload/conflicts
app.include_router(upload.router,     prefix="/upload",    tags=["Document Ingestion (PDF)"])
app.include_router(csv_upload.router, prefix="/upload",    tags=["File Upload (CSV)"])
app.include_router(rag.router,        prefix="/rag",       tags=["RAG Engine"])
app.include_router(inventory.router,  prefix="/inventory", tags=["Inventory Management"])
app.include_router(agent.router,      prefix="/agent",     tags=["Multi-Agent Orchestrator"])

@app.get("/", tags=["Health Check"])
async def root():
    return {
        "status": "online",
        "system": "SCM AI Control Tower v3 — Supervisor-Judge Architecture",
        "agents_active": ["Supervisor", "Inventory", "Supplier", "Shipment", "Report", "Judge"],
        "api_key_configured": bool(os.getenv("GROQ_API_KEY")),
        "db_configured": bool(os.getenv("DATABASE_URL"))
    }

@app.post("/system/reset", tags=["System"])
async def system_reset():
    # Reset SQLite tables
    await reset_db()
    # Reset ChromaDB
    try:
        rag.chroma_client.delete_collection("pdf_chunks")
        rag.collection = rag.chroma_client.get_or_create_collection(
            name="pdf_chunks",
            metadata={"hnsw:space": "cosine"}
        )
    except Exception as e:
        print(f"[WARN] Failed to delete ChromaDB collection: {e}")
    return {"status": "success", "message": "System reset to clean state"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
