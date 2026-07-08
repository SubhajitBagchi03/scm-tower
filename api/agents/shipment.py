from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime, timedelta

from api.llm_client import acomplete


class ShipmentRecord(BaseModel):
    shipment_id: str
    product_id: Optional[str] = None
    quantity: Optional[int] = None
    supplier: Optional[str] = None
    carrier: Optional[str] = None
    expected_delivery: Optional[str] = None
    actual_delivery: Optional[str] = None
    is_on_time: Optional[bool] = None
    carrier_avg_delay: float = 0.0
    urgency_factor: float = 1.0


class ShipmentAnalysis(BaseModel):
    shipment_id: str
    predicted_delay_days: float
    risk_level: str               # High Risk | Medium Risk | Low Risk
    confidence_score: float
    recommended_actions: List[str]
    alternative_routes: List[str]
    reasoning: str
    cascade_risk: Optional[str] = None   # stockout warning if delay hits inventory
    carrier_reliability: Optional[str] = None  # anomaly flag


class ShipmentAgent:
    def __init__(self):
        self.weather_impact      = 0.5
        self.peak_season_impact  = 0.3

    def get_season_impact(self) -> float:
        """Q4 peak season adds extra delay risk."""
        month = datetime.now().month
        if 10 <= month <= 12:
            return self.peak_season_impact
        return 0.0

    def calculate_predicted_delay(self, record: ShipmentRecord) -> float:
        """
        Predicted Delay = (carrier_avg_delay + weather + season) × urgency_factor
        urgency_factor > 1 means we're extra sensitive to delays
        """
        season_impact = self.get_season_impact()
        base_delay    = record.carrier_avg_delay + self.weather_impact + season_impact
        return round(base_delay * record.urgency_factor, 1)

    def assess_risk(
        self,
        predicted_delay: float,
        days_until_delivery: int
    ) -> tuple[str, float]:
        """
        Returns (risk_level, confidence_score)
        High:   delay > 3 days OR delivery in < 1 day
        Medium: delay > 1 day  OR delivery in < 3 days
        Low:    on track
        Confidence increases when multiple signals agree.
        """
        signals = 0
        if predicted_delay > 3:   signals += 2
        elif predicted_delay > 1: signals += 1
        if days_until_delivery < 1:  signals += 2
        elif days_until_delivery < 3: signals += 1

        if signals >= 3:
            return "High Risk", round(min(0.65 + (signals * 0.05), 0.95), 2)
        elif signals >= 1:
            return "Medium Risk", round(0.55 + (signals * 0.05), 2)
        return "Low Risk", 0.80

    def detect_carrier_anomaly(
        self,
        carrier: str,
        all_shipments: List[dict]
    ) -> Optional[str]:
        """
        Anomaly detection: if a carrier has been late more than 60%
        of the time in the last 10 shipments, flag them as unreliable.
        """
        if not all_shipments or not carrier:
            return None

        carrier_shipments = [
            s for s in all_shipments
            if str(s.get("carrier", "")).lower() == carrier.lower()
        ]

        # Only analyze last 10
        recent = carrier_shipments[-10:]
        if len(recent) < 3:
            return None  # not enough data

        late_count = sum(
            1 for s in recent
            if str(s.get("is_on_time", "1")) in ["0", "False", "false"]
        )
        late_rate = late_count / len(recent)

        if late_rate > 0.6:
            return (
                f"⚠️ CARRIER ANOMALY: {carrier} has been late "
                f"{late_count}/{len(recent)} recent shipments "
                f"({late_rate*100:.0f}% late rate). Consider switching carriers."
            )
        elif late_rate > 0.4:
            return (
                f"⚡ CARRIER WARNING: {carrier} showing elevated delay rate "
                f"({late_rate*100:.0f}%). Monitor closely."
            )
        return None

    def detect_cascade_risk(
        self,
        record: ShipmentRecord,
        predicted_delay: float,
        inventory_items: List[dict]
    ) -> Optional[str]:
        """
        Cascade detection: if this shipment is delayed, will the affected
        product hit a stockout before it arrives?

        Checks: current_stock - (avg_daily_consumption × delay_days) < safety_stock
        """
        if not record.product_id or not inventory_items:
            return None

        # Find matching inventory item
        product = next(
            (
                item for item in inventory_items
                if str(item.get("product_id", "")).lower() == record.product_id.lower()
                or str(item.get("product_name", "")).lower() == record.product_id.lower()
            ),
            None
        )

        if not product:
            return None

        current_stock     = product.get("quantity_in_stock", 0)
        reorder_threshold = product.get("reorder_threshold", 0)
        avg_daily         = product.get("avg_daily_consumption")

        # If avg_daily not in DB, estimate from threshold
        if not avg_daily or avg_daily <= 0:
            avg_daily = reorder_threshold / 14 if reorder_threshold > 0 else 1.0

        # Project stock after the delay period
        stock_after_delay = current_stock - (avg_daily * predicted_delay)

        if stock_after_delay <= 0:
            return (
                f"🚨 STOCKOUT CASCADE: Delay of {predicted_delay} days on "
                f"{record.product_id} will cause a STOCKOUT. "
                f"Current stock ({current_stock}) will be depleted in "
                f"{int(current_stock / avg_daily)} days. Expedite immediately."
            )
        elif stock_after_delay <= reorder_threshold:
            return (
                f"⚠️ LOW STOCK CASCADE: Delay on {record.product_id} will push "
                f"stock ({current_stock} → {stock_after_delay:.0f}) "
                f"below reorder threshold ({reorder_threshold}). Prioritize this shipment."
            )
        return None

    async def analyze_shipment(
        self,
        record: ShipmentRecord,
        all_shipments: List[dict] = None,
        inventory_items: List[dict] = None
    ) -> ShipmentAnalysis:

        # Time until delivery
        try:
            eta                 = datetime.fromisoformat(record.expected_delivery)
            days_until_delivery = (eta - datetime.now()).days
        except Exception:
            days_until_delivery = 5  # default if date missing/invalid

        predicted_delay = self.calculate_predicted_delay(record)
        risk, confidence = self.assess_risk(predicted_delay, days_until_delivery)

        # Carrier anomaly detection
        carrier_flag = self.detect_carrier_anomaly(
            record.carrier or "",
            all_shipments or []
        )

        # Cascade detection
        cascade_flag = self.detect_cascade_risk(
            record,
            predicted_delay,
            inventory_items or []
        )

        # Escalate risk if cascade detected
        if cascade_flag and risk != "High Risk":
            risk       = "High Risk"
            confidence = min(confidence + 0.10, 0.95)

        # Actions based on risk
        actions = ["Monitor tracking closely"]
        routes  = ["Standard Ground (current)"]

        if risk == "High Risk":
            actions = [
                "Contact carrier immediately for status update",
                "Prepare customer/operations delay notification",
                "Activate emergency same-day backup supplier if cascade risk",
                "Escalate to supply chain manager"
            ]
            routes = [
                "Premium Express (Next Day Air)",
                "Air Freight (1-2 days)",
                "Local emergency supplier"
            ]
        elif risk == "Medium Risk":
            actions = [
                "Request real-time tracking update from carrier",
                "Prepare internal alert for operations team",
                "Identify backup supplier as precaution"
            ]
            routes = [
                "Expedited Ground (+1 day speed)",
                "Regional hub rerouting"
            ]

        season_impact = self.get_season_impact()
        reasoning = (
            f"Carrier '{record.carrier}' has {record.carrier_avg_delay}d avg delay. "
            f"Weather adds {self.weather_impact}d, "
            f"season adds {season_impact}d. "
            f"Urgency factor: {record.urgency_factor}x. "
            f"Predicted delay: {predicted_delay}d. "
            f"ETA in {days_until_delivery} days."
        )

        return ShipmentAnalysis(
            shipment_id=record.shipment_id,
            predicted_delay_days=predicted_delay,
            risk_level=risk,
            confidence_score=confidence,
            recommended_actions=actions,
            alternative_routes=routes,
            reasoning=reasoning,
            cascade_risk=cascade_flag,
            carrier_reliability=carrier_flag
        )

    async def generate_contextual_reasoning(
        self,
        analysis: ShipmentAnalysis,
        cross_agent_context: str = "",
    ) -> str:
        """
        T2.2 — LLM-powered contextual reasoning that explains the delay risk
        in the context of current inventory levels (cross-agent context).
        Falls back to deterministic summary if LLM fails.
        """
        prompt = f"""You are a supply chain specialist explaining a shipment delay risk.

SHIPMENT ANALYSIS:
  Shipment ID: {analysis.shipment_id}
  Risk Level:  {analysis.risk_level}
  Predicted Delay: {analysis.predicted_delay_days} days
  Cascade Risk: {analysis.cascade_risk or 'None detected'}
  Carrier Reliability: {analysis.carrier_reliability or 'Normal'}

CROSS-AGENT CONTEXT (inventory findings):
{cross_agent_context or 'No cross-agent context available.'}

Formulaic reasoning already computed: {analysis.reasoning}

Write 2 concise sentences explaining the risk:
1. What is the primary risk driver (carrier, weather, season).
2. How does this impact the inventory based on the context above (is there a stockout threat?).
Be specific with numbers. Do not use bullet points.
"""
        try:
            return await acomplete(prompt, temperature=0.2, max_tokens=200)
        except Exception:
            parts = [f"Shipment {analysis.shipment_id} assessed as {analysis.risk_level} with {analysis.predicted_delay_days}d predicted delay."]
            if analysis.cascade_risk:
                parts.append("Warning: Cascade risk detected affecting downstream inventory.")
            elif cross_agent_context:
                parts.append("Assessed in context of current inventory levels.")
            return " ".join(parts)