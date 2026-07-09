"""
Agent API Router — refactored for the Supervisor-Judge agentic architecture.

Every action now goes through the orchestrator:
  orchestrate() → Supervisor plan → Agents → Judge → Response + Trace

Maintains full backward compatibility with the existing API contract.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from sqlalchemy import select
from io import BytesIO

from database import AsyncSessionLocal
from models import Inventory, Supplier, Shipment

from api.agents.orchestrator import orchestrate
from api.agents.report import generate_report_pdf, ReportAgent
from api.rag import rag_query, QueryRequest as RagQueryRequest

router = APIRouter()

_report_ai = ReportAgent()


# ── Request / Response Models ────────────────────────────────

class AgentRequest(BaseModel):
    action: str
    product_id: Optional[str] = None
    query: Optional[str] = None
    quantity: Optional[int] = 100
    urgency: Optional[str] = "normal"
    shipment_id: Optional[str] = None


class ReportPdfRequest(BaseModel):
    assessment_result: Optional[str] = None
    judge_status: Optional[str] = None
    judge_reasoning: Optional[str] = None


class AgentResponse(BaseModel):
    result: Optional[str] = None
    issue: Optional[Dict[str, Any]] = None
    recommendation: Optional[Any] = None
    reasoning: Optional[str] = None
    context: Optional[str] = None
    kpis: Optional[Dict[str, Any]] = None
    cascade_risk: Optional[str] = None
    carrier_flag: Optional[str] = None
    root_causes: Optional[List[str]] = None
    forward_projections: Optional[List[str]] = None
    # New: agentic fields
    trace: Optional[Dict[str, Any]] = None
    judge_verdict: Optional[Dict[str, Any]] = None


# ── DB Helpers ───────────────────────────────────────────────

async def fetch_inventory_from_db() -> List[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Inventory).where(Inventory.is_active == True)
        )
        items = result.scalars().all()
        return [
            {
                "product_id": i.product_id,
                "product_name": i.product_name,
                "quantity_in_stock": i.quantity_in_stock,
                "reorder_threshold": i.reorder_threshold,
                "warehouse": i.warehouse,
                "supplier_info": i.supplier_info,
                "unit_cost": i.unit_cost,
                "avg_daily_consumption": i.avg_daily_consumption,
                "lead_time_days": i.lead_time_days,
            }
            for i in items
        ]


async def fetch_suppliers_from_db() -> List[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Supplier).where(Supplier.is_active == True)
        )
        rows = result.scalars().all()
        return [
            {
                "supplier_name": s.supplier_name,
                "base_cost_per_unit": s.base_cost_per_unit,
                "on_time_delivery_rate": s.on_time_delivery_rate,
                "lead_time_days": s.lead_time_days,
                "quality_rating": s.quality_rating,
                "historical_issues": s.historical_issues,
                "contact_info": s.contact_info,
            }
            for s in rows
        ]


async def fetch_shipments_from_db() -> List[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Shipment).where(Shipment.is_active == True)
        )
        rows = result.scalars().all()
        return [
            {
                "shipment_id": s.shipment_id,
                "product_id": s.product_id,
                "quantity": s.quantity,
                "supplier": s.supplier,
                "carrier": s.carrier,
                "expected_delivery": s.expected_delivery,
                "actual_delivery": s.actual_delivery,
                "is_on_time": s.is_on_time,
                "carrier_avg_delay": s.carrier_avg_delay,
            }
            for s in rows
        ]


# ── Main Agent Controller ─────────────────────────────────────

@router.post("/", response_model=AgentResponse)
async def agent_controller(req: AgentRequest):
    """
    Single entry point for all agent actions.
    All actions now route through the Supervisor-Judge orchestration pipeline.
    """
    # Handle ask/document query separately (RAG pipeline + optional DB query)
    if req.action in ("ask_document", "ask"):
        if not req.query:
            raise HTTPException(status_code=400, detail="query required for ask action")
        try:
            data = await rag_query(RagQueryRequest(question=req.query))
            return AgentResponse(
                result=data.get("answer", "No answer found"),
                context=f"Sources: {len(data.get('sources', []))} document(s)",
                recommendation={"sources": data.get("sources", [])},
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

    # Validate action
    valid_actions = {
        "analyze_inventory", "select_supplier", "track_shipment",
        "generate_report", "full_assessment",
    }
    if req.action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {req.action}. Valid actions: {sorted(valid_actions)}"
        )

    # Validate required params per action
    if req.action == "analyze_inventory" and not req.product_id:
        raise HTTPException(status_code=400, detail="product_id required for analyze_inventory")
    if req.action == "track_shipment" and not req.shipment_id:
        raise HTTPException(status_code=400, detail="shipment_id required for track_shipment")

    # Fetch data
    inventory = await fetch_inventory_from_db()
    suppliers = await fetch_suppliers_from_db()
    shipments = await fetch_shipments_from_db()

    if not inventory:
        return AgentResponse(
            result="No inventory data found. Upload an inventory CSV first.",
            context="Use POST /upload/preview to upload data.",
        )

    # Build params dict for orchestrator
    params = {
        "product_id": req.product_id,
        "quantity": req.quantity or 100,
        "urgency": req.urgency or "normal",
        "shipment_id": req.shipment_id,
        "query": req.query,
    }

    try:
        # THE CORE: everything now goes through the Supervisor-Judge pipeline
        result = await orchestrate(
            action=req.action,
            params=params,
            inventory=inventory,
            suppliers=suppliers,
            shipments=shipments,
        )
        return AgentResponse(**result)

    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Orchestration failed: {str(e)}\n\n{err_msg}"
        )


# ── PDF Download Endpoint ────────────────────────────────────

@router.get("/report/pdf")
async def download_report_pdf():
    inventory = await fetch_inventory_from_db()
    shipments = await fetch_shipments_from_db()
    suppliers = await fetch_suppliers_from_db()

    if not inventory:
        raise HTTPException(
            status_code=400,
            detail="No inventory data found. Upload an inventory CSV first."
        )

    report = await _report_ai.create_weekly_report(inventory, shipments, suppliers)
    pdf_bytes = generate_report_pdf(report)
    filename = f"scm_report_{report.timestamp.replace(' ', '_').replace(':', '-')}.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/report/pdf_context")
async def download_report_pdf_context(req: ReportPdfRequest):
    inventory = await fetch_inventory_from_db()
    shipments = await fetch_shipments_from_db()
    suppliers = await fetch_suppliers_from_db()

    if not inventory:
        raise HTTPException(
            status_code=400,
            detail="No inventory data found. Upload an inventory CSV first."
        )

    report = await _report_ai.create_weekly_report(
        inventory_data=inventory, 
        shipment_data=shipments, 
        supplier_data=suppliers,
        assessment_result=req.assessment_result,
        judge_status=req.judge_status,
        judge_reasoning=req.judge_reasoning
    )
    pdf_bytes = generate_report_pdf(report)
    filename = f"scm_report_{report.timestamp.replace(' ', '_').replace(':', '-')}.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )