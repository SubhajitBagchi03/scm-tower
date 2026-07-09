"""
RAG Engine — Retrieval-Augmented Generation over indexed PDF documents.

Simplified from v2:
- Removed ROUGE/BLEU evaluation (methodologically incorrect — measured overlap with input, not accuracy)
- Removed faithfulness LLM evaluation (replaced by Judge Agent in the agentic pipeline)
- Kept: embedding, retrieval, generation, source citations, inventory context injection
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import chromadb
import os
import traceback
from sqlalchemy import select

from database import AsyncSessionLocal
from models import Inventory
from api.llm_client import get_embedding, acomplete

router = APIRouter()

chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(
    name="pdf_chunks",
    metadata={"hnsw:space": "cosine"}
)


# ── Schema ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    use_only_last_document: bool = False


# ── Embedding ───────────────────────────────────────────────

def _get_embedding(text: str) -> list[float]:
    return get_embedding(text)


# ── Last Document Helper ─────────────────────────────────────

def get_last_uploaded_document() -> str | None:
    try:
        all_docs = collection.get(include=["metadatas"])
        if not all_docs or not all_docs.get("metadatas"):
            return None
        latest_doc = None
        latest_ts = None
        for meta in all_docs["metadatas"]:
            ts = meta.get("upload_timestamp")
            if ts and (latest_ts is None or ts > latest_ts):
                latest_ts = ts
                latest_doc = meta.get("source")
        return latest_doc or (all_docs["metadatas"][-1].get("source") if all_docs["metadatas"] else None)
    except Exception:
        return None


# ── Inventory → Text (for live-data questions) ───────────────

async def inventory_to_text_chunks() -> list[str]:
    chunks = []
    async with AsyncSessionLocal() as db:
        # LIMIT to 50 to prevent exploding the LLM context window (TPM limit)
        result = await db.execute(
            select(Inventory).where(Inventory.is_active == True).limit(50)
        )
        items = result.scalars().all()
        for item in items:
            status = "Low Stock" if item.quantity_in_stock < item.reorder_threshold else "Normal"
            text = (
                f"Product {item.product_id} ({item.product_name}) "
                f"has {item.quantity_in_stock} units in stock. "
                f"Reorder threshold is {item.reorder_threshold}. "
                f"Inventory status is {status}."
            )
            if item.supplier_info:
                text += f" Supplier: {item.supplier_info}."
            chunks.append(text)
    return chunks


# ── Question Type Detection ──────────────────────────────────

def is_inventory_question(question: str) -> bool:
    """Route to live DB data vs PDF documents."""
    inventory_keywords = ["inventory", "stock level", "reorder", "quantity in stock", "units in stock"]
    policy_keywords = ["penalty", "sla", "policy", "procedure", "contract", "rate", "compliance", "standard"]
    q = question.lower()
    if any(kw in q for kw in policy_keywords):
        return False
    return any(kw in q for kw in inventory_keywords)


# ── RAG Query ────────────────────────────────────────────────

@router.post("/")
async def rag_query(payload: QueryRequest):
    try:
        question = payload.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="Question is empty")

        query_embedding = _get_embedding(question)

        # Optional: filter to last uploaded document only
        where_filter = None
        if payload.use_only_last_document:
            last_doc = get_last_uploaded_document()
            if last_doc:
                where_filter = {"source": last_doc}

        # Retrieve from ChromaDB
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(payload.top_k, 10),
            where=where_filter,
            include=["documents", "metadatas"],
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        inventory_keywords = ["inventory", "stock level", "reorder", "quantity in stock", "units in stock"]
        mentions_inventory = any(kw in question.lower() for kw in inventory_keywords)

        # Include live inventory data if the question mentions inventory
        inventory_chunks = []
        if mentions_inventory and not payload.use_only_last_document:
            inventory_chunks = await inventory_to_text_chunks()

        # We no longer clear documents! We pass BOTH PDF documents and DB chunks to the LLM.

        if not documents and not inventory_chunks:
            return {
                "answer": "No relevant information found. Please upload PDF documents or inventory data first.",
                "sources": [],
                "filtered_to_last_document": payload.use_only_last_document,
            }

        context = "\n\n".join(documents + inventory_chunks)

        prompt = f"""You are a supply chain intelligence assistant. Answer the question below using ONLY the provided context, which includes both uploaded policy documents and live database inventory records.

Instructions:
- Be precise and include specific details (numbers, names, dates)
- Structure your answer clearly
- If the answer is not in the context, state that clearly

Context:
{context}

Question:
{question}

Answer:"""

        answer = await acomplete(prompt)

        # Build source citations (kept — genuinely useful for traceability)
        sources = [
            {
                "text": doc,
                "source": meta.get("source", ""),
                "page": meta.get("page", ""),
            }
            for doc, meta in zip(documents, metadatas)
        ]

        # Show sources if any PDF documents were retrieved
        show_sources = len(documents) > 0

        return {
            "question": question,
            "answer": answer,
            "sources": sources if show_sources else [],
            "show_sources": show_sources,
            "filtered_to_last_document": payload.use_only_last_document,
            "document_used": (
                get_last_uploaded_document()
                if payload.use_only_last_document else "all"
            ),
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"RAG query failed: {str(e)}"
        )
