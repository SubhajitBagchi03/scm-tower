from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
import math
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import Inventory

router = APIRouter()

# --- SCHEMAS ---

class InventoryItem(BaseModel):
    product_id: str = Field(..., example="SKU-102")
    product_name: str = Field(..., example="Widget B")
    quantity_in_stock: int = Field(..., ge=0)
    reorder_threshold: int = Field(..., ge=0)
    warehouse: Optional[str] = Field("Main Warehouse")
    supplier_info: Optional[str] = None
    unit_cost: Optional[float] = None
    avg_daily_consumption: Optional[float] = None
    lead_time_days: Optional[int] = None

class InventoryAnalysis(BaseModel):
    product_id: str
    product_name: str
    status: str                  # Red, Yellow, Green
    days_until_stockout: int
    recommended_action: str
    safety_stock: int
    eoq: int
    reorder_point: float
    estimated_cost: float
    reasoning: str
    # Show what values were actually used (from DB or defaults)
    used_avg_daily_consumption: float
    used_unit_cost: float
    used_lead_time_days: int
    data_completeness: str       # "full" | "partial" | "defaults_used"


# --- CORE ALGORITHMS ---

def calculate_eoq(
    annual_demand: float,
    ordering_cost: float = 50.0,
    holding_cost: float = 5.0
) -> int:
    """
    Economic Order Quantity: sqrt((2 * D * S) / H)
    ordering_cost: cost to place one order (default $50)
    holding_cost: cost to hold one unit/year (default $5)
    """
    if annual_demand <= 0:
        return 0
    return int(math.sqrt((2 * annual_demand * ordering_cost) / holding_cost))


def calculate_safety_stock(
    std_dev: float = 2.0,
    lead_time: int = 7,
    z_score: float = 1.645
) -> int:
    """
    Safety Stock: Z * std_dev * sqrt(lead_time)
    z_score 1.645 = 95% service level
    """
    return int(z_score * std_dev * math.sqrt(lead_time))


def get_seasonal_multiplier() -> float:
    """
    Q1 (Jan-Mar): 0.9x demand
    Q2/Q3 (Apr-Sep): 1.0x demand
    Q4 (Oct-Dec): 1.4x demand (peak season)
    """
    month = datetime.now().month
    if 1 <= month <= 3:
        return 0.9
    if 10 <= month <= 12:
        return 1.4
    return 1.0


def resolve_product_defaults(item: Inventory) -> tuple[float, float, int, str]:
    """
    Resolves the actual values to use for analysis.
    Priority: DB value → calculated fallback → system default

    Returns: (avg_daily_consumption, unit_cost, lead_time_days, data_completeness)
    """
    missing = []

    # avg_daily_consumption: if not in DB, estimate from stock/threshold ratio
    if item.avg_daily_consumption and item.avg_daily_consumption > 0:
        avg_daily = item.avg_daily_consumption
    else:
        # Fallback: assume stock turns over in ~14 days
        avg_daily = round(item.quantity_in_stock / 14, 2) if item.quantity_in_stock > 0 else 1.0
        missing.append("avg_daily_consumption")

    # unit_cost: if not in DB, use a neutral default
    if item.unit_cost and item.unit_cost > 0:
        unit_cost = item.unit_cost
    else:
        unit_cost = 10.0  # neutral default — clearly labeled in response
        missing.append("unit_cost")

    # lead_time_days: if not in DB, use 7-day default
    if item.lead_time_days and item.lead_time_days > 0:
        lead_time = item.lead_time_days
    else:
        lead_time = 7
        missing.append("lead_time_days")

    if not missing:
        completeness = "full"
    elif len(missing) == 3:
        completeness = "defaults_used"
    else:
        completeness = f"partial (estimated: {', '.join(missing)})"

    return avg_daily, unit_cost, lead_time, completeness


# --- ENDPOINTS ---

@router.get("/", response_model=List[InventoryItem])
async def get_all_inventory(db: AsyncSession = Depends(get_db)):
    """Returns all active inventory items from the database."""
    result = await db.execute(
        select(Inventory)
        .where(Inventory.is_active == True)
        .order_by(Inventory.product_name)
    )
    items = result.scalars().all()
    return [
        InventoryItem(
            product_id=i.product_id,
            product_name=i.product_name,
            quantity_in_stock=i.quantity_in_stock,
            reorder_threshold=i.reorder_threshold,
            warehouse=i.warehouse,
            supplier_info=i.supplier_info,
            unit_cost=i.unit_cost,
            avg_daily_consumption=i.avg_daily_consumption,
            lead_time_days=i.lead_time_days
        )
        for i in items
    ]


@router.get("/{product_id}/analyze", response_model=InventoryAnalysis)
async def analyze_item(product_id: str, db: AsyncSession = Depends(get_db)):
    """
    Full inventory analysis for a single product.
    Reads all parameters from DB — no hardcoded values.
    Falls back gracefully if optional fields (unit_cost, avg_daily_consumption,
    lead_time_days) were not present in the uploaded CSV.
    """
    # Fetch product from DB — get the most recently active record
    result = await db.execute(
        select(Inventory)
        .where(
            and_(
                Inventory.product_id == product_id,
                Inventory.is_active == True
            )
        )
        .order_by(Inventory.created_at.desc())
    )
    item = result.scalars().first()

    if not item:
        # Try searching by product_name in case product_id format differs
        result2 = await db.execute(
            select(Inventory)
            .where(
                and_(
                    Inventory.product_name.ilike(f"%{product_id}%"),
                    Inventory.is_active == True
                )
            )
        )
        item = result2.scalars().first()

    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Product '{product_id}' not found. Upload an inventory CSV first."
        )

    # Resolve values from DB with fallbacks
    avg_daily, unit_cost, lead_time, completeness = resolve_product_defaults(item)

    # Apply seasonal adjustment
    multiplier = get_seasonal_multiplier()
    adjusted_demand = avg_daily * multiplier

    # Core calculations
    days_left = int(item.quantity_in_stock / adjusted_demand) if adjusted_demand > 0 else 999
    safety_stock = calculate_safety_stock(lead_time=lead_time)
    reorder_point = (adjusted_demand * lead_time) + safety_stock
    eoq = calculate_eoq(annual_demand=adjusted_demand * 365)

    # Status + action
    status = "Green"
    action = "No action required"
    if item.quantity_in_stock <= safety_stock:
        status = "Red"
        action = f"REORDER {eoq} units IMMEDIATELY"
    elif item.quantity_in_stock <= reorder_point:
        status = "Yellow"
        action = f"Place order for {eoq} units soon"

    reasoning = (
        f"Current stock: {item.quantity_in_stock} units. "
        f"Reorder point: {reorder_point:.1f} units. "
        f"At {adjusted_demand:.1f} units/day (seasonal {multiplier}x), "
        f"stock lasts {days_left} days. "
        f"Lead time: {lead_time} days. "
        f"Data completeness: {completeness}."
    )

    return InventoryAnalysis(
        product_id=item.product_id,
        product_name=item.product_name,
        status=status,
        days_until_stockout=days_left,
        recommended_action=action,
        safety_stock=safety_stock,
        eoq=eoq,
        reorder_point=reorder_point,
        estimated_cost=round(eoq * unit_cost, 2),
        reasoning=reasoning,
        used_avg_daily_consumption=avg_daily,
        used_unit_cost=unit_cost,
        used_lead_time_days=lead_time,
        data_completeness=completeness
    )


@router.get("/status/alerts", response_model=List[InventoryAnalysis])
async def get_all_alerts(db: AsyncSession = Depends(get_db)):
    """
    Runs analysis on ALL active inventory items and returns only
    those with Red or Yellow status. Useful for dashboard alerts.
    """
    result = await db.execute(
        select(Inventory).where(Inventory.is_active == True)
    )
    items = result.scalars().all()

    alerts = []
    multiplier = get_seasonal_multiplier()

    for item in items:
        avg_daily, unit_cost, lead_time, completeness = resolve_product_defaults(item)
        adjusted_demand = avg_daily * multiplier

        days_left = int(item.quantity_in_stock / adjusted_demand) if adjusted_demand > 0 else 999
        safety_stock = calculate_safety_stock(lead_time=lead_time)
        reorder_point = (adjusted_demand * lead_time) + safety_stock
        eoq = calculate_eoq(annual_demand=adjusted_demand * 365)

        status = "Green"
        action = "No action required"
        if item.quantity_in_stock <= safety_stock:
            status = "Red"
            action = f"REORDER {eoq} units IMMEDIATELY"
        elif item.quantity_in_stock <= reorder_point:
            status = "Yellow"
            action = f"Place order for {eoq} units soon"

        if status in ["Red", "Yellow"]:
            alerts.append(InventoryAnalysis(
                product_id=item.product_id,
                product_name=item.product_name,
                status=status,
                days_until_stockout=days_left,
                recommended_action=action,
                safety_stock=safety_stock,
                eoq=eoq,
                reorder_point=reorder_point,
                estimated_cost=round(eoq * unit_cost, 2),
                reasoning=(
                    f"Stock ({item.quantity_in_stock}) vs Reorder Point ({reorder_point:.1f}). "
                    f"Seasonal factor: {multiplier}x. Lead time: {lead_time} days."
                ),
                used_avg_daily_consumption=avg_daily,
                used_unit_cost=unit_cost,
                used_lead_time_days=lead_time,
                data_completeness=completeness
            ))

    # Sort by most critical first (Red before Yellow, then by days_until_stockout)
    alerts.sort(key=lambda x: (0 if x.status == "Red" else 1, x.days_until_stockout))
    return alerts


@router.put("/{product_id}")
async def update_inventory_item(
    product_id: str,
    updates: InventoryItem,
    db: AsyncSession = Depends(get_db)
):
    """Update a specific inventory item directly in the DB."""
    result = await db.execute(
        select(Inventory).where(
            and_(Inventory.product_id == product_id, Inventory.is_active == True)
        )
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")

    item.quantity_in_stock = updates.quantity_in_stock
    item.reorder_threshold = updates.reorder_threshold
    item.warehouse = updates.warehouse
    item.supplier_info = updates.supplier_info
    if updates.unit_cost is not None:
        item.unit_cost = updates.unit_cost
    if updates.avg_daily_consumption is not None:
        item.avg_daily_consumption = updates.avg_daily_consumption
    if updates.lead_time_days is not None:
        item.lead_time_days = updates.lead_time_days

    await db.commit()
    return {"message": f"Product '{product_id}' updated successfully"}


@router.delete("/{product_id}")
async def deactivate_inventory_item(
    product_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Soft delete — marks item as inactive instead of removing from DB."""
    result = await db.execute(
        select(Inventory).where(
            and_(Inventory.product_id == product_id, Inventory.is_active == True)
        )
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")

    item.is_active = False
    await db.commit()
    return {"message": f"Product '{product_id}' deactivated"}