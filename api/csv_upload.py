import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import UploadedFile, Inventory, Supplier, Shipment, Conflict
from api.normalization import run_normalization_pipeline

router = APIRouter()

# In-memory staging store: file_id → normalized pipeline result
# This holds data between /preview and /commit without writing to DB yet
_staging: Dict[str, dict] = {}


# ─────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────

class ConflictResolution(BaseModel):
    product_name: str
    field_name: str
    resolution: str  # "use_existing" | "use_incoming" | "keep_both"

class CommitRequest(BaseModel):
    file_id: str
    confirmed_mapping: Optional[Dict[str, str]] = None   # user can correct AI column mapping
    missing_field_defaults: Optional[Dict[str, Any]] = None  # user fills in missing required fields
    conflict_resolutions: Optional[List[ConflictResolution]] = []


# ─────────────────────────────────────────────
# HELPER: Fetch existing rows from DB for conflict detection
# ─────────────────────────────────────────────

async def get_existing_rows(file_type: str, db: AsyncSession) -> tuple[list[dict], Optional[str]]:
    """Returns existing active rows and the file_id they came from."""
    if file_type == "inventory":
        result = await db.execute(select(Inventory).where(Inventory.is_active == True))
        rows = result.scalars().all()
        existing = [
            {
                "product_name": r.product_name,
                "product_id": r.product_id,
                "quantity_in_stock": r.quantity_in_stock,
                "reorder_threshold": r.reorder_threshold,
                "unit_cost": r.unit_cost,
                "avg_daily_consumption": r.avg_daily_consumption,
                "lead_time_days": r.lead_time_days,
                "warehouse": r.warehouse,
                "_file_id": r.file_id
            }
            for r in rows
        ]
    elif file_type == "supplier":
        result = await db.execute(select(Supplier).where(Supplier.is_active == True))
        rows = result.scalars().all()
        existing = [
            {
                "supplier_name": r.supplier_name,
                "base_cost_per_unit": r.base_cost_per_unit,
                "on_time_delivery_rate": r.on_time_delivery_rate,
                "lead_time_days": r.lead_time_days,
                "quality_rating": r.quality_rating,
                "historical_issues": r.historical_issues,
                "_file_id": r.file_id
            }
            for r in rows
        ]
    elif file_type == "shipment":
        result = await db.execute(select(Shipment).where(Shipment.is_active == True))
        rows = result.scalars().all()
        existing = [
            {
                "shipment_id": r.shipment_id,
                "carrier": r.carrier,
                "expected_delivery": r.expected_delivery,
                "quantity": r.quantity,
                "supplier": r.supplier,
                "carrier_avg_delay": r.carrier_avg_delay,
                "_file_id": r.file_id
            }
            for r in rows
        ]
    else:
        existing = []

    existing_file_id = existing[0]["_file_id"] if existing else None
    return existing, existing_file_id


# ─────────────────────────────────────────────
# ENDPOINT 1: POST /upload/preview
# Normalizes the file and returns a preview — does NOT save to DB yet
# ─────────────────────────────────────────────

@router.post("/preview")
async def preview_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    # Read file content
    try:
        content = (await file.read()).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read file. Ensure it is UTF-8 encoded.")

    if not content.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Generate a unique ID for this upload session
    file_id = str(uuid.uuid4())

    # Run the normalization pipeline (type detection + AI mapping + conflict detection)
    try:
        # We need to detect file type first to fetch existing rows
        # Run a quick first pass just for type detection
        from io import StringIO
        import pandas as pd
        df_temp = pd.read_csv(StringIO(content))
        headers = list(df_temp.columns)
        sample = df_temp.head(3).to_dict(orient="records")

        from api.normalization import detect_file_type
        file_type = await detect_file_type(headers, sample)

        # Fetch existing DB rows for conflict detection
        existing_rows, existing_file_id = await get_existing_rows(file_type, db)

        # Run full pipeline
        result = await run_normalization_pipeline(
            csv_content=content,
            file_id=file_id,
            existing_db_rows=existing_rows,
            existing_file_id=existing_file_id
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Normalization failed: {str(e)}")

    # Stage the result in memory (keyed by file_id)
    _staging[file_id] = {
        **result,
        "original_filename": file.filename,
    }

    # Return preview to frontend — frontend shows this for user confirmation
    return {
        "file_id":          file_id,
        "original_filename": file.filename,
        "file_type":        result["file_type"],
        "total_rows":       result["total_rows"],
        "column_mapping":   result["column_mapping"],
        "missing_required": result["missing_required"],
        "preview_rows":     result["preview_rows"],
        "conflicts":        result["conflicts"],
        "can_commit":       result["can_commit"],
        "message": (
            "Ready to commit. Review the mapping and conflicts before confirming."
            if result["can_commit"]
            else f"Cannot commit yet. Missing required fields: {result['missing_required']}"
        )
    }


# ─────────────────────────────────────────────
# ENDPOINT 2: POST /upload/commit
# User has reviewed the preview and confirmed — now save to DB
# ─────────────────────────────────────────────

@router.post("/commit")
async def commit_upload(
    req: CommitRequest,
    db: AsyncSession = Depends(get_db)
):
    # Retrieve staged data
    staged = _staging.get(req.file_id)
    if not staged:
        raise HTTPException(
            status_code=404,
            detail="No staged upload found for this file_id. Please re-upload the file."
        )

    file_type = staged["file_type"]
    rows = staged["all_rows"]

    # Apply user-corrected column mapping if provided
    # (Rows are already normalized; confirmed_mapping is stored for audit trail only)
    # Future: re-normalize with corrected mapping if needed

    # Apply user-provided defaults for missing fields
    if req.missing_field_defaults:
        for row in rows:
            for field, default_val in req.missing_field_defaults.items():
                if row.get(field) is None:
                    row[field] = default_val

    # Check again if required fields are now satisfied
    from api.normalization import SCHEMAS
    schema = SCHEMAS[file_type]
    still_missing = [
        f for f in schema["required"]
        if not all(row.get(f) is not None and str(row.get(f)).strip() != "" for row in rows)
    ]
    if still_missing:
        raise HTTPException(
            status_code=400,
            detail=f"Still missing required fields: {still_missing}. Provide defaults."
        )

    # Build resolution lookup: (product_name, field_name) → resolution
    # Priority: manual user override > auto-applied AI resolution > default (use_incoming)
    resolution_map = {}

    # 1. Auto-apply high-confidence AI resolutions from staged preview (T4.2)
    staged_conflicts = staged.get("conflicts", [])
    for c in staged_conflicts:
        if c.get("auto_applied") and c.get("ai_resolution"):
            key = (str(c.get("product_name", "")).lower(), c["field_name"])
            resolution_map[key] = c["ai_resolution"]

    # 2. Manual user overrides always win (applied last)
    if req.conflict_resolutions:
        for res in req.conflict_resolutions:
            resolution_map[(res.product_name.lower(), res.field_name)] = res.resolution

    # ── Save UploadedFile record ──
    uploaded_file = UploadedFile(
        file_id=req.file_id,
        original_filename=staged["original_filename"],
        file_type=file_type,
        row_count=len(rows),
        status="confirmed",
        column_mapping=staged["column_mapping"]
    )
    db.add(uploaded_file)

    # ── Save rows based on file type ──
    saved_count = 0

    if file_type == "inventory":
        for row in rows:
            product_name = str(row.get("product_name", "")).lower()

            # Handle conflicts: if use_incoming, deactivate existing record first
            for field in ["quantity_in_stock", "reorder_threshold", "unit_cost",
                          "avg_daily_consumption", "lead_time_days"]:
                resolution = resolution_map.get((product_name, field))
                if resolution == "use_existing":
                    # Skip this row entirely — keep existing
                    break
                elif resolution == "use_incoming":
                    # Deactivate existing record for this product
                    existing = await db.execute(
                        select(Inventory).where(
                            and_(
                                Inventory.product_name.ilike(row.get("product_name", "")),
                                Inventory.is_active == True
                            )
                        )
                    )
                    for old in existing.scalars().all():
                        old.is_active = False
                    break
                # "keep_both" → just insert new record alongside existing
            else:
                # No conflict or keep_both — just insert
                pass
            # Deactivate existing active records for same product before inserting new
            existing_records = await db.execute(
                select(Inventory).where(
                    and_(
                        Inventory.product_name == row.get("product_name"),
                        Inventory.is_active == True
                    )
                )
            )
            for old in existing_records.scalars().all():
                old.is_active = False
            item = Inventory(
                file_id=req.file_id,
                product_id=row.get("product_id", f"AUTO-{uuid.uuid4().hex[:6].upper()}"),
                product_name=row.get("product_name"),
                quantity_in_stock=row.get("quantity_in_stock", 0),
                reorder_threshold=row.get("reorder_threshold", 0),
                warehouse=row.get("warehouse", "Main Warehouse"),
                supplier_info=row.get("supplier_info"),
                unit_cost=row.get("unit_cost"),
                avg_daily_consumption=row.get("avg_daily_consumption"),
                lead_time_days=row.get("lead_time_days"),
                is_active=True
            )
            db.add(item)
            saved_count += 1

    elif file_type == "supplier":
        for row in rows:
            supplier_name = str(row.get("supplier_name", "")).lower()

            for field in ["base_cost_per_unit", "on_time_delivery_rate", "lead_time_days"]:
                resolution = resolution_map.get((supplier_name, field))
                if resolution == "use_existing":
                    break
                elif resolution == "use_incoming":
                    existing = await db.execute(
                        select(Supplier).where(
                            and_(
                                Supplier.supplier_name.ilike(row.get("supplier_name", "")),
                                Supplier.is_active == True
                            )
                        )
                    )
                    for old in existing.scalars().all():
                        old.is_active = False
                    break
            else:
                pass

            supplier = Supplier(
                file_id=req.file_id,
                supplier_name=row.get("supplier_name"),
                base_cost_per_unit=row.get("base_cost_per_unit", 0.0),
                on_time_delivery_rate=row.get("on_time_delivery_rate", 0.0),
                lead_time_days=row.get("lead_time_days", 7),
                quality_rating=row.get("quality_rating", 3.0),
                historical_issues=row.get("historical_issues", 0),
                contact_info=row.get("contact_info"),
                is_active=True
            )
            db.add(supplier)
            saved_count += 1

    elif file_type == "shipment":
        for row in rows:
            shipment = Shipment(
                file_id=req.file_id,
                shipment_id=row.get("shipment_id", f"SHP-{uuid.uuid4().hex[:6].upper()}"),
                product_id=row.get("product_id"),
                quantity=row.get("quantity"),
                supplier=row.get("supplier"),
                carrier=row.get("carrier"),
                expected_delivery=row.get("expected_delivery"),
                actual_delivery=row.get("actual_delivery"),
                is_on_time=row.get("is_on_time"),
                carrier_avg_delay=row.get("carrier_avg_delay", 0.0),
                is_active=True
            )
            db.add(shipment)
            saved_count += 1

    # ── Save conflict records ──
    for conflict in staged.get("conflicts", []):
        product_name = str(conflict.get("product_name", "")).lower()
        field_name = conflict.get("field_name", "")
        resolution = resolution_map.get((product_name, field_name), "keep_both")

        conflict_record = Conflict(
            table_name=conflict["table_name"],
            product_name=conflict["product_name"],
            file_id_a=conflict["file_id_a"],
            file_id_b=conflict["file_id_b"],
            field_name=field_name,
            value_a=conflict["value_a"],
            value_b=conflict["value_b"],
            resolution=resolution,
            resolved_at=datetime.utcnow() if resolution else None
        )
        db.add(conflict_record)

    # ── Commit to DB ──
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Database commit failed: {str(e)}")

    # Clear staging memory
    del _staging[req.file_id]

    return {
        "message": "Upload committed successfully",
        "file_id": req.file_id,
        "file_type": file_type,
        "rows_saved": saved_count,
        "conflicts_recorded": len(staged.get("conflicts", []))
    }


# ─────────────────────────────────────────────
# ENDPOINT 3: GET /upload/files
# List all uploaded files
# ─────────────────────────────────────────────

@router.get("/files")
async def list_uploaded_files(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UploadedFile).order_by(UploadedFile.upload_timestamp.desc())
    )
    files = result.scalars().all()
    return [
        {
            "file_id": f.file_id,
            "filename": f.original_filename,
            "file_type": f.file_type,
            "row_count": f.row_count,
            "status": f.status,
            "uploaded_at": str(f.upload_timestamp),
            "column_mapping": f.column_mapping
        }
        for f in files
    ]


# ─────────────────────────────────────────────
# ENDPOINT 4: GET /upload/conflicts
# List all unresolved conflicts
# ─────────────────────────────────────────────

@router.get("/conflicts")
async def list_conflicts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conflict).order_by(Conflict.id.desc())
    )
    conflicts = result.scalars().all()
    return [
        {
            "id": c.id,
            "table": c.table_name,
            "product_name": c.product_name,
            "field": c.field_name,
            "existing_value": c.value_a,
            "incoming_value": c.value_b,
            "resolution": c.resolution,
            "resolved_at": str(c.resolved_at) if c.resolved_at else None
        }
        for c in conflicts
    ]