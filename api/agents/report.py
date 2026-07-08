import os
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from api.llm_client import acomplete
from datetime import datetime
from io import BytesIO

# PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable
)



# ── Pydantic Models ──────────────────────────────────────────

class ReportKPIs(BaseModel):
    inventory_health: float
    shipment_on_time_rate: float
    supplier_health_score: float
    critical_alerts_count: int
    items_below_reorder: int
    projected_stockouts_14d: int


class ExecutiveReport(BaseModel):
    timestamp: str
    kpis: ReportKPIs
    executive_summary: str
    recommendations: List[str]
    root_causes: List[str]
    forward_projections: List[str]


# ── Report Agent ─────────────────────────────────────────────

class ReportAgent:
    def __init__(self):
        self.target_health = 90.0

    def calculate_inventory_health(self, items: List[dict]) -> float:
        if not items:
            return 0.0
        low_stock = sum(
            1 for item in items
            if item.get("quantity_in_stock", 0) < item.get("reorder_point", item.get("reorder_threshold", 0))
        )
        return round((1 - (low_stock / len(items))) * 100, 2)

    def calculate_shipment_on_time(self, shipments: List[dict]) -> float:
        if not shipments:
            return 0.0
        on_time = sum(
            1 for s in shipments
            if str(s.get("is_on_time", "")).lower() in ["true", "1", "yes"]
        )
        return round((on_time / len(shipments)) * 100, 2)

    def calculate_supplier_health(self, suppliers: List[dict]) -> float:
        if not suppliers:
            return 0.0
        scores = []
        for s in suppliers:
            on_time       = float(s.get("on_time_delivery_rate", 0.8))
            quality       = float(s.get("quality_rating", 3.0)) / 5
            issues        = int(s.get("historical_issues", 0))
            issue_penalty = max(0, 1 - (issues * 0.1))
            score = (on_time * 0.5) + (quality * 0.3) + (issue_penalty * 0.2)
            scores.append(score)
        return round((sum(scores) / len(scores)) * 100, 2)

    def calculate_forward_projections(self, items: List[dict]) -> tuple[int, List[str]]:
        warnings       = []
        stockout_count = 0
        for item in items:
            stock     = item.get("quantity_in_stock", 0)
            threshold = item.get("reorder_threshold", 0)
            avg_daily = item.get("avg_daily_consumption")
            if not avg_daily or avg_daily <= 0:
                avg_daily = threshold / 14 if threshold > 0 else 1.0
            days_left = int(stock / avg_daily) if avg_daily > 0 else 999
            if days_left <= 14:
                stockout_count += 1
                warnings.append(
                    f"{item.get('product_name', 'Unknown')} "
                    f"(stock: {stock}, ~{days_left}d remaining)"
                )
        return stockout_count, warnings

    def detect_root_causes(
        self,
        items: List[dict],
        shipments: List[dict],
        suppliers: List[dict]
    ) -> List[str]:
        causes = []

        supplier_issues: Dict[str, int] = {}
        for item in items:
            if item.get("quantity_in_stock", 0) < item.get("reorder_point", item.get("reorder_threshold", 0)):
                supplier = item.get("supplier_info", "Unknown")
                supplier_issues[supplier] = supplier_issues.get(supplier, 0) + 1
        for supplier, count in supplier_issues.items():
            if count >= 2:
                causes.append(
                    f"Supplier '{supplier}' linked to {count} low-stock products — "
                    f"review supplier reliability or lead times."
                )

        carrier_delays: Dict[str, list] = {}
        for s in shipments:
            carrier    = s.get("carrier", "Unknown")
            is_on_time = str(s.get("is_on_time", "1")).lower() in ["true", "1", "yes"]
            carrier_delays.setdefault(carrier, []).append(is_on_time)
        for carrier, records in carrier_delays.items():
            if len(records) >= 3:
                late_rate = 1 - (sum(records) / len(records))
                if late_rate > 0.5:
                    causes.append(
                        f"Carrier '{carrier}' has {late_rate*100:.0f}% late rate "
                        f"over {len(records)} shipments — consider switching carriers."
                    )

        warehouse_issues: Dict[str, int] = {}
        for item in items:
            if item.get("quantity_in_stock", 0) < item.get("reorder_point", item.get("reorder_threshold", 0)):
                wh = item.get("warehouse", "Unknown")
                warehouse_issues[wh] = warehouse_issues.get(wh, 0) + 1
        for wh, count in warehouse_issues.items():
            if count >= 3:
                causes.append(
                    f"Warehouse '{wh}' has {count} products below reorder threshold — "
                    f"check replenishment process for this location."
                )

        for s in suppliers:
            issues = int(s.get("historical_issues", 0))
            if issues >= 2:
                causes.append(
                    f"Supplier '{s.get('supplier_name', 'Unknown')}' has "
                    f"{issues} recorded incidents — assess risk of continued use."
                )

        return list(dict.fromkeys(causes)) if causes else ["No significant root causes detected in current data."]

    async def generate_summary(
        self,
        kpis: ReportKPIs,
        root_causes: List[str],
        projections: List[str]
    ) -> str:
        causes_text      = "\n".join(f"- {c}" for c in root_causes)
        projections_text = "\n".join(f"- {p}" for p in projections) if projections else "None"
        prompt = f"""
You are a senior supply chain analyst writing an executive summary for a weekly report.

Current KPIs:
- Inventory Health: {kpis.inventory_health}% (Target: 90%)
- Shipment On-Time Rate: {kpis.shipment_on_time_rate}%
- Supplier Health Score: {kpis.supplier_health_score}%
- Critical Alerts: {kpis.critical_alerts_count}
- Items Below Reorder: {kpis.items_below_reorder}
- Products Projected to Stockout in 14 Days: {kpis.projected_stockouts_14d}

Root Causes Identified:
{causes_text}

Products at Stockout Risk:
{projections_text}

Write a concise 3-4 sentence executive summary. Be direct about risks.
Focus on what needs immediate attention and why. Do not use bullet points.
"""
        try:
            return await acomplete(prompt)
        except Exception:
            return f"Weekly executive summary generated. Inventory health is {kpis.inventory_health}% with {kpis.critical_alerts_count} critical alerts. Review the root causes and recommendations below."

    async def create_weekly_report(
        self,
        inventory_data: List[dict],
        shipment_data: List[dict],
        supplier_data: List[dict] = None
    ) -> ExecutiveReport:

        suppliers = supplier_data or []

        for idx, item in enumerate(inventory_data):
            if not item.get("product_id"):
                item["product_id"] = f"AUTO-{idx+1}"
            if not item.get("product_name"):
                item["product_name"] = f"Unknown Product {idx+1}"
            if item.get("quantity_in_stock") is None:
                item["quantity_in_stock"] = 0
            if item.get("reorder_threshold") is None:
                item["reorder_threshold"] = 1
        for s in suppliers:
            if s.get("on_time_delivery_rate") is None:
                s["on_time_delivery_rate"] = 0.8
            if s.get("quality_rating") is None:
                s["quality_rating"] = 3.0
            if s.get("historical_issues") is None:
                s["historical_issues"] = 0
        for s in shipment_data:
            if s.get("is_on_time") is None:
                s["is_on_time"] = True

        inv_health  = self.calculate_inventory_health(inventory_data)
        ship_rate   = self.calculate_shipment_on_time(shipment_data)
        supp_health = self.calculate_supplier_health(suppliers)

        critical_count = sum(
            1 for item in inventory_data
            if item.get("quantity_in_stock", 0) < (item.get("reorder_point", item.get("reorder_threshold", 0)) * 0.5)
        )
        below_reorder = sum(
            1 for item in inventory_data
            if item.get("quantity_in_stock", 0) < item.get("reorder_point", item.get("reorder_threshold", 0))
        )

        stockout_count, stockout_warnings = self.calculate_forward_projections(inventory_data)

        kpis = ReportKPIs(
            inventory_health=inv_health,
            shipment_on_time_rate=ship_rate,
            supplier_health_score=supp_health,
            critical_alerts_count=critical_count,
            items_below_reorder=below_reorder,
            projected_stockouts_14d=stockout_count
        )

        root_causes = self.detect_root_causes(inventory_data, shipment_data, suppliers)
        summary     = await self.generate_summary(kpis, root_causes, stockout_warnings)

        recommendations = []
        if inv_health < 90:
            recommendations.append(
                f"Inventory health at {inv_health}% — below 90% target. "
                f"Initiate reorder for {below_reorder} products immediately."
            )
        if stockout_count > 0:
            recommendations.append(
                f"{stockout_count} products projected to stockout within 14 days: "
                + ", ".join(stockout_warnings[:3])
                + ("..." if len(stockout_warnings) > 3 else "")
            )
        if ship_rate < 85:
            recommendations.append(
                f"Shipment on-time rate at {ship_rate}% — review carrier contracts "
                f"and consider switching underperforming carriers."
            )
        if supp_health < 75:
            recommendations.append(
                f"Supplier health score at {supp_health}% — audit suppliers with "
                f"historical issues and low quality ratings."
            )
        if not recommendations:
            recommendations.append("All KPIs within acceptable ranges. Continue monitoring.")

        return ExecutiveReport(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
            kpis=kpis,
            executive_summary=summary,
            recommendations=recommendations,
            root_causes=root_causes,
            forward_projections=stockout_warnings
        )


# ── PDF Generator ─────────────────────────────────────────────

def generate_report_pdf(report: ExecutiveReport) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"],
        fontSize=22, textColor=colors.HexColor("#1a1a2e"), spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"],
        fontSize=10, textColor=colors.HexColor("#666666"), spaceAfter=16
    )
    section_style = ParagraphStyle(
        "SectionHeader", parent=styles["Heading2"],
        fontSize=13, textColor=colors.HexColor("#1a1a2e"),
        spaceBefore=16, spaceAfter=6
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=10, leading=15, textColor=colors.HexColor("#333333")
    )
    bullet_style = ParagraphStyle(
        "Bullet", parent=body_style,
        leftIndent=16, spaceBefore=3
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"],
        fontSize=8, textColor=colors.HexColor("#999999"), alignment=1
    )

    story = []

    story.append(Paragraph("SCM AI Control Tower", title_style))
    story.append(Paragraph(
        f"Weekly Executive Report &nbsp;|&nbsp; Generated: {report.timestamp}",
        subtitle_style
    ))
    story.append(HRFlowable(
        width="100%", thickness=2,
        color=colors.HexColor("#1a1a2e"), spaceAfter=12
    ))

    story.append(Paragraph("Key Performance Indicators", section_style))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=colors.HexColor("#cccccc"), spaceAfter=8
    ))

    kpi_data = [
        ["Metric", "Value", "Status"],
        ["Inventory Health",
         f"{report.kpis.inventory_health}%",
         "OK" if report.kpis.inventory_health >= 90 else "Below Target"],
        ["Shipment On-Time Rate",
         f"{report.kpis.shipment_on_time_rate}%",
         "OK" if report.kpis.shipment_on_time_rate >= 85 else "Below Target"],
        ["Supplier Health Score",
         f"{report.kpis.supplier_health_score}%",
         "OK" if report.kpis.supplier_health_score >= 75 else "Below Target"],
        ["Critical Alerts",
         str(report.kpis.critical_alerts_count),
         "None" if report.kpis.critical_alerts_count == 0 else "Action Needed"],
        ["Items Below Reorder",
         str(report.kpis.items_below_reorder),
         "None" if report.kpis.items_below_reorder == 0 else "Reorder Required"],
        ["Projected Stockouts (14d)",
         str(report.kpis.projected_stockouts_14d),
         "None" if report.kpis.projected_stockouts_14d == 0 else "Urgent"],
    ]

    kpi_table = Table(kpi_data, colWidths=[3 * inch, 1.5 * inch, 2.5 * inch])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0),  11),
        ("ALIGN",          (0, 0), (-1, -1), "LEFT"),
        ("ALIGN",          (1, 0), (1, -1),  "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#f8f9fa"), colors.white]),
        ("FONTNAME",       (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",       (0, 1), (-1, -1), 10),
        ("GRID",           (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
        ("LEFTPADDING",    (0, 0), (-1, -1), 10),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Executive Summary", section_style))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=colors.HexColor("#cccccc"), spaceAfter=8
    ))
    story.append(Paragraph(report.executive_summary, body_style))

    story.append(Paragraph("Recommendations", section_style))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=colors.HexColor("#cccccc"), spaceAfter=8
    ))
    for i, rec in enumerate(report.recommendations, 1):
        story.append(Paragraph(f"{i}. {rec}", bullet_style))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Root Cause Analysis", section_style))
    story.append(HRFlowable(
        width="100%", thickness=0.5,
        color=colors.HexColor("#cccccc"), spaceAfter=8
    ))
    for cause in report.root_causes:
        story.append(Paragraph(f"- {cause}", bullet_style))
    story.append(Spacer(1, 8))

    if report.forward_projections:
        story.append(Paragraph("14-Day Stockout Risk", section_style))
        story.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#cccccc"), spaceAfter=8
        ))
        proj_data = [["Product", "Status"]]
        for p in report.forward_projections:
            proj_data.append([p, "At Risk"])
        proj_table = Table(proj_data, colWidths=[4.5 * inch, 2 * inch])
        proj_table.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  colors.HexColor("#e74c3c")),
            ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
            ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",       (0, 0), (-1, -1), 10),
            ("ALIGN",          (0, 0), (-1, -1), "LEFT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.HexColor("#fff5f5"), colors.white]),
            ("GRID",           (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
            ("TOPPADDING",     (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 7),
            ("LEFTPADDING",    (0, 0), (-1, -1), 10),
        ]))
        story.append(proj_table)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(
        width="100%", thickness=1,
        color=colors.HexColor("#1a1a2e"), spaceBefore=8
    ))
    story.append(Paragraph(
        f"Generated by SCM AI Control Tower &nbsp;|&nbsp; "
        f"{report.timestamp} &nbsp;|&nbsp; Confidential",
        footer_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()