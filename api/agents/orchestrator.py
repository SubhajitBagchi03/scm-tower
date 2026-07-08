"""
Orchestrator — the main execution engine of the multi-agent system.

This is the single entry point that replaces the if/elif chain in agent.py.

Flow for every action:
  1. Create AgentContext (shared memory)
  2. Supervisor creates a plan (LLM-powered, with fallback)
  3. Execute each planned agent step in order
     a. Provide cross-agent context to each agent
     b. After each step, Supervisor checks if plan needs adapting
     c. Store findings in context so next agent can reference them
  4. Supervisor synthesizes all findings (LLM-powered)
  5. Judge validates the full output (LLM + deterministic)
  6. Return trace + verdict + result in the API response

The specialist agents (supplier.py, shipment.py, report.py) remain mostly
unchanged — the orchestrator wraps them with context injection and trace recording.
"""

import math
import time
import os
import json
import re
from datetime import datetime as dt
from typing import Any, Dict, List, Optional

from api.llm_client import acomplete
from api.config import inventory_config, supplier_config

from api.agents.context import AgentContext, AgentTrace, JudgeVerdict
from api.agents.supervisor import SupervisorAgent
from api.agents.judge import JudgeAgent

# Existing specialist agents
from api.agents.supplier import SupplierAgent, SupplierProfile
from api.agents.shipment import ShipmentAgent, ShipmentRecord
from api.agents.report import ReportAgent, ExecutiveReport

_supervisor = SupervisorAgent()
_judge = JudgeAgent()
_supplier_ai = SupplierAgent()
_shipment_ai = ShipmentAgent()
_report_ai = ReportAgent()


# ─────────────────────────────────────────────
# SPECIALIST AGENT WRAPPERS
# Each wrapper:
#   1. Reads cross-agent context
#   2. Runs the existing domain logic (formulas, etc.)
#   3. Adds LLM reasoning on top
#   4. Writes findings back to context
#   5. Records the step in the trace
# ─────────────────────────────────────────────

async def _run_inventory_agent(
    context: AgentContext,
    inventory: List[dict],
    suppliers: List[dict],
    task: str,
) -> dict:
    """Inventory analysis with cross-agent context and LLM reasoning."""
    t0 = time.time()

    if not inventory:
        context.add_step(
            agent_name="inventory_agent",
            task=task,
            finding="No inventory data found in database.",
            data={},
            confidence=0.0,
            duration_ms=int((time.time() - t0) * 1000),
        )
        return {}

    month = dt.now().month
    multiplier = inventory_config.seasonal_pattern.get(month, 1.0)

    critical_items = []
    warning_items = []
    all_analyzed = []

    for item in inventory:
        avg_daily = item.get("avg_daily_consumption") or (
            item["reorder_threshold"] / 14 if item.get("reorder_threshold", 0) > 0 else 1.0
        )
        lead_time = item.get("lead_time_days") or 7
        unit_cost = item.get("unit_cost") or 10.0
        adjusted = avg_daily * multiplier

        safety_stock = int(
            inventory_config.service_level_z_score
            * inventory_config.demand_std_dev_days
            * math.sqrt(lead_time)
        )
        reorder_point = (adjusted * lead_time) + safety_stock
        eoq = int(math.sqrt(
            (2 * adjusted * 365 * inventory_config.ordering_cost)
            / inventory_config.holding_cost
        )) if adjusted > 0 else 0
        days_left = int(item["quantity_in_stock"] / adjusted) if adjusted > 0 else 999

        status = "Green"
        if item["quantity_in_stock"] <= safety_stock:
            status = "Red"
        elif item["quantity_in_stock"] <= reorder_point:
            status = "Yellow"

        # Mutate the item in-place so downstream agents use the dynamic calculations
        item["status"] = status
        item["days_left"] = days_left
        item["safety_stock"] = safety_stock
        item["reorder_point"] = round(reorder_point, 1)
        item["eoq"] = eoq
        item["avg_daily_consumption"] = avg_daily
        item["estimated_cost"] = round(eoq * unit_cost, 2)

        analyzed = {**item}
        all_analyzed.append(analyzed)

        if status == "Red":
            critical_items.append(analyzed)
        elif status == "Yellow":
            warning_items.append(analyzed)

    # Store critical items in context for other agents
    context.critical_inventory_items = critical_items + warning_items

    # Build result data
    result = {
        "total_items": len(inventory),
        "critical_count": len(critical_items),
        "warning_count": len(warning_items),
        "healthy_count": len(inventory) - len(critical_items) - len(warning_items),
        "critical_items": critical_items[:5],
        "warning_items": warning_items[:5],
        "seasonal_multiplier": multiplier,
        "overall_status": (
            "critical" if critical_items else
            "warning" if warning_items else "healthy"
        ),
    }
    context.findings["inventory"] = result

    # Add deep-dive details if analyzing a single item
    item_details = ""
    if len(all_analyzed) == 1:
        single_item = all_analyzed[0]
        item_details = (
            f" Details for {single_item.get('product_name', 'item')}: "
            f"Stock={single_item.get('quantity_in_stock')}, "
            f"EOQ={single_item.get('eoq')}, SafetyStock={single_item.get('safety_stock')}, "
            f"ReorderPoint={single_item.get('reorder_point')}."
        )

    # LLM reasoning — wraps the formula results with cross-agent context
    cross_context = context.get_cross_agent_context_for("inventory_agent")
    reasoning = await _generate_agent_reasoning(
        agent="Inventory Agent",
        task=task,
        data_summary=(
            f"Analyzed {len(inventory)} items. "
            f"{len(critical_items)} critical (Red), {len(warning_items)} warning (Yellow). "
            f"Critical items: {', '.join(i.get('product_name', '') for i in critical_items[:3])}. "
            f"Seasonal demand multiplier: {multiplier}x.{item_details}"
        ),
        cross_context=cross_context,
    )

    finding = (
        f"{len(critical_items)} critical item(s) and {len(warning_items)} warning item(s) "
        f"out of {len(inventory)} total."
        if (critical_items or warning_items) else
        f"All {len(inventory)} items are healthy."
    )

    context.add_step(
        agent_name="inventory_agent",
        task=task,
        finding=finding,
        data={**result, "reasoning": reasoning},
        confidence=0.85,
        duration_ms=int((time.time() - t0) * 1000),
    )

    return result


async def _run_supplier_agent(
    context: AgentContext,
    suppliers: List[dict],
    task: str,
    quantity: int = 100,
    urgency: str = "normal",
) -> dict:
    """Supplier selection with cross-agent context and LLM reasoning."""
    t0 = time.time()

    if not suppliers:
        context.add_step(
            agent_name="supplier_agent",
            task=task,
            finding="No supplier data found in database.",
            data={},
            confidence=0.0,
            duration_ms=int((time.time() - t0) * 1000),
        )
        return {}

    # Escalate urgency if cascades were detected (cross-agent awareness)
    if context.cascade_risks:
        urgency = "immediate"
    elif context.critical_inventory_items and urgency == "normal":
        urgency = "urgent"

    is_urgent = urgency in ("urgent", "immediate")

    profiles = [
        SupplierProfile(
            name=s["supplier_name"],
            base_cost_per_unit=float(s["base_cost_per_unit"]),
            on_time_delivery_rate=float(s["on_time_delivery_rate"]),
            lead_time_days=int(s["lead_time_days"]),
            quality_rating=float(s["quality_rating"]),
            historical_issues=int(s.get("historical_issues", 0)),
            contact_info=s.get("contact_info"),
        )
        for s in suppliers
    ]

    scores = await _supplier_ai.select_best_supplier(profiles, quantity, is_urgent)
    best = scores[0] if scores else None

    if best:
        context.recommended_suppliers = [s.dict() for s in scores[:3]]

    result = {
        "urgency_used": urgency,
        "quantity": quantity,
        "best_supplier": best.dict() if best else None,
        "all_scores": [s.dict() for s in scores],
        "weights_used": _supplier_ai.get_dynamic_weights(is_urgent, quantity),
    }
    context.findings["supplier"] = result

    # LLM reasoning with cross-agent context
    cross_context = context.get_cross_agent_context_for("supplier_agent")
    reasoning = await _generate_agent_reasoning(
        agent="Supplier Agent",
        task=task,
        data_summary=(
            f"Ranked {len(scores)} suppliers. Best: {best.name if best else 'N/A'} "
            f"(score: {best.final_score:.3f}, cost: ${best.total_cost:,.2f}, "
            f"risk: {best.risk_score:.2f}). "
            f"Urgency applied: {urgency}."
        ),
        cross_context=cross_context,
    )

    context.add_step(
        agent_name="supplier_agent",
        task=task,
        finding=(
            f"Best supplier: {best.name} (score {best.final_score:.2f}, "
            f"${best.total_cost:,.0f} for {quantity} units, {urgency} urgency)."
            if best else "No suppliers available."
        ),
        data={**result, "reasoning": reasoning},
        confidence=0.82,
        duration_ms=int((time.time() - t0) * 1000),
    )

    return result


async def _run_shipment_agent(
    context: AgentContext,
    shipments: List[dict],
    inventory: List[dict],
    task: str,
    target_shipment_id: Optional[str] = None,
    urgency: str = "normal",
) -> dict:
    """Shipment analysis with cascade detection and cross-agent context."""
    t0 = time.time()

    if not shipments:
        context.add_step(
            agent_name="shipment_agent",
            task=task,
            finding="No shipment data found in database.",
            data={},
            confidence=0.0,
            duration_ms=int((time.time() - t0) * 1000),
        )
        return {}

    # If specific shipment requested, focus there first
    if target_shipment_id:
        shipments_to_check = [
            s for s in shipments
            if s.get("shipment_id", "").lower() == target_shipment_id.lower()
        ]
        if not shipments_to_check:
            shipments_to_check = shipments
    else:
        shipments_to_check = shipments

    high_risk = []
    medium_risk = []
    new_cascades = []

    for s in shipments_to_check:
        record = ShipmentRecord(
            shipment_id=s["shipment_id"],
            product_id=s.get("product_id"),
            quantity=s.get("quantity"),
            supplier=s.get("supplier"),
            carrier=s.get("carrier"),
            expected_delivery=s.get("expected_delivery") or "2099-12-31",
            carrier_avg_delay=float(s.get("carrier_avg_delay") or 0),
            urgency_factor=1.5 if urgency in ("urgent", "immediate") else 1.0,
            is_on_time=s.get("is_on_time"),
            actual_delivery=s.get("actual_delivery"),
        )

        analysis = await _shipment_ai.analyze_shipment(
            record,
            all_shipments=shipments,
            inventory_items=inventory,
        )

        shipment_data = {
            "shipment_id": s["shipment_id"],
            "risk": analysis.risk_level,
            "predicted_delay": analysis.predicted_delay_days,
            "cascade": analysis.cascade_risk,
            "carrier_flag": analysis.carrier_reliability,
            "confidence": analysis.confidence_score,
            "reasoning": analysis.reasoning,
            "actions": analysis.recommended_actions,
        }

        if analysis.cascade_risk:
            new_cascades.append(analysis.cascade_risk)

        if analysis.risk_level == "High Risk":
            high_risk.append(shipment_data)
        elif analysis.risk_level == "Medium Risk":
            medium_risk.append(shipment_data)

    # Write cascades to context so Supervisor and Supplier Agent can react
    context.cascade_risks.extend(new_cascades)
    context.high_risk_shipments = high_risk

    # Pick the most severe carrier flag to surface at top level
    top_carrier_flag = next(
        (s["carrier_flag"] for s in high_risk if s.get("carrier_flag")), None
    ) or next(
        (s["carrier_flag"] for s in medium_risk if s.get("carrier_flag")), None
    )

    result = {
        "total_checked": len(shipments_to_check),
        "high_risk_count": len(high_risk),
        "medium_risk_count": len(medium_risk),
        "cascade_count": len(new_cascades),
        "high_risk_shipments": high_risk[:5],
        "cascade_risks": new_cascades[:5],
        "carrier_flag": top_carrier_flag,
    }
    context.findings["shipment"] = result

    # LLM reasoning
    cross_context = context.get_cross_agent_context_for("shipment_agent")
    reasoning = await _generate_agent_reasoning(
        agent="Shipment Agent",
        task=task,
        data_summary=(
            f"Checked {len(shipments_to_check)} shipment(s). "
            f"{len(high_risk)} high risk, {len(medium_risk)} medium risk. "
            f"{len(new_cascades)} cascade risk(s) detected."
        ),
        cross_context=cross_context,
    )

    context.add_step(
        agent_name="shipment_agent",
        task=task,
        finding=(
            f"{len(high_risk)} high-risk shipment(s), {len(new_cascades)} cascade risk(s) "
            f"across {len(shipments_to_check)} shipments."
        ),
        data={**result, "reasoning": reasoning},
        confidence=0.80,
        duration_ms=int((time.time() - t0) * 1000),
    )

    return result


async def _run_report_agent(
    context: AgentContext,
    inventory: List[dict],
    shipments: List[dict],
    suppliers: List[dict],
    task: str,
) -> dict:
    """Report generation using the full cross-agent context."""
    t0 = time.time()

    report: ExecutiveReport = await _report_ai.create_weekly_report(
        inventory_data=inventory,
        shipment_data=shipments,
        supplier_data=suppliers,
    )

    result = {
        "kpis": report.kpis.dict(),
        "executive_summary": report.executive_summary,
        "recommendations": report.recommendations,
        "root_causes": report.root_causes,
        "forward_projections": report.forward_projections,
        "timestamp": report.timestamp,
        "report_object": report,   # kept for PDF generation
    }
    context.findings["report"] = {k: v for k, v in result.items() if k != "report_object"}

    context.add_step(
        agent_name="report_agent",
        task=task,
        finding=(
            f"KPIs: Inventory health {report.kpis.inventory_health:.0f}%, "
            f"On-time {report.kpis.shipment_on_time_rate:.0f}%, "
            f"Supplier health {report.kpis.supplier_health_score:.0f}%. "
            f"{report.kpis.projected_stockouts_14d} stockout(s) projected in 14 days."
        ),
        data={k: v for k, v in result.items() if k != "report_object"},
        confidence=0.88,
        duration_ms=int((time.time() - t0) * 1000),
    )

    return result


# ─────────────────────────────────────────────
# LLM REASONING HELPER
# ─────────────────────────────────────────────

async def _generate_agent_reasoning(
    agent: str,
    task: str,
    data_summary: str,
    cross_context: str,
) -> str:
    """
    Adds LLM-generated contextual reasoning on top of formula results.
    This is what makes agents truly agentic — not just math, but interpretation.
    Has a deterministic fallback.
    """
    prompt = f"""You are the {agent} in a supply chain AI system.

Your task: {task}

Your analysis results:
{data_summary}

Context from other agents that ran before you:
{cross_context}

In 2-3 sentences, explain:
1. What your results mean in the context of the overall supply chain situation
2. Any important cross-domain connection you can see (e.g., how your findings relate to what other agents found)
3. The most critical action that should be taken based on your analysis

Be specific, use numbers, and focus on what a supply chain manager needs to hear. No bullet points.
"""
    try:
        return await acomplete(prompt)
    except Exception:
        return data_summary  # Fallback: return the plain data summary


# ─────────────────────────────────────────────
# MAIN ORCHESTRATION FUNCTION
# ─────────────────────────────────────────────

async def orchestrate(
    action: str,
    params: Dict[str, Any],
    inventory: List[dict],
    suppliers: List[dict],
    shipments: List[dict],
) -> Dict[str, Any]:
    """
    Main entry point. Called by the FastAPI router.
    Replaces the if/elif chain in the old agent.py.

    Returns a dict with all response fields PLUS trace and judge_verdict.
    """
    t0 = time.time()

    # 1. Build shared context and filter data if needed
    goal = _build_goal_description(action, params)
    context = AgentContext(goal=goal, action=action, params=params)

    # Filter inventory if a specific product is requested
    if action == "analyze_inventory" and params.get("product_id"):
        target = params["product_id"].lower()
        inventory = [i for i in inventory if str(i.get("product_id", "")).lower() == target]
        if not inventory:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Product {params['product_id']} not found in inventory.")
        
        # Also filter shipments to only those relevant to this product
        shipments = [s for s in shipments if str(s.get("product_id", "")).lower() == target]

    data_summary = (
        f"{len(inventory)} inventory items, "
        f"{len(suppliers)} suppliers, "
        f"{len(shipments)} shipments available."
    )

    # 2. Supervisor creates the plan
    plan = await _supervisor.create_plan(
        action=action,
        params=params,
        data_summary=data_summary,
    )
    context.set_plan(plan)

    # Record the supervisor's planning step
    context.add_step(
        agent_name="supervisor",
        task="Create execution plan",
        finding=f"Planned {len(plan.steps)} step(s): {' → '.join(s.agent for s in plan.steps)}",
        data={"plan": plan.dict(), "reasoning": plan.reasoning},
        confidence=0.9,
        duration_ms=0,
    )

    # 3. Execute agents in plan order
    remaining_steps = list(plan.steps)
    step_index = 0

    while remaining_steps:
        current_step = remaining_steps.pop(0)
        agent_name = current_step.agent
        task = current_step.task

        # Dispatch to the right agent wrapper
        if agent_name == "inventory_agent":
            await _run_inventory_agent(context, inventory, suppliers, task)

        elif agent_name == "supplier_agent":
            qty = params.get("quantity") or 100
            # If we found critical items, use their EOQ as quantity
            if context.critical_inventory_items:
                qty = max(
                    context.critical_inventory_items[0].get("eoq", qty),
                    qty
                )
            await _run_supplier_agent(
                context, suppliers, task,
                quantity=qty,
                urgency=params.get("urgency", "normal"),
            )

        elif agent_name == "shipment_agent":
            await _run_shipment_agent(
                context, shipments, inventory, task,
                target_shipment_id=params.get("shipment_id"),
                urgency=params.get("urgency", "normal"),
            )

        elif agent_name == "report_agent":
            await _run_report_agent(context, inventory, shipments, suppliers, task)

        step_index += 1

        # 4. Supervisor checks if remaining plan needs adaptation
        if remaining_steps:
            adapted = await _supervisor.should_adapt_plan(context, remaining_steps)
            if adapted:
                context.add_step(
                    agent_name="supervisor",
                    task="Adapt execution plan",
                    finding=f"Plan adapted: {' → '.join(s.agent for s in adapted)}",
                    data={"adapted_steps": [s.dict() for s in adapted]},
                    confidence=0.85,
                    duration_ms=0,
                )
                remaining_steps = adapted

    # 5. Supervisor synthesizes all findings
    synthesis = await _supervisor.synthesize(context)

    # 6. Judge validates the full output
    judge_verdict: JudgeVerdict = await _judge.validate(context)

    # 7. Build the final trace
    trace: AgentTrace = context.to_trace(synthesis=synthesis, judge_verdict=judge_verdict)

    # 8. Build the API response dict (maintaining backward compatibility)
    response = _build_response(context, synthesis, trace, judge_verdict)

    return response


# ─────────────────────────────────────────────
# RESPONSE BUILDER
# ─────────────────────────────────────────────

def _build_response(
    context: AgentContext,
    synthesis: str,
    trace: AgentTrace,
    judge_verdict: JudgeVerdict,
) -> Dict[str, Any]:
    """
    Maps agent findings back to the AgentResponse fields.
    Maintains full backward compatibility with the existing API contract
    while adding trace and judge_verdict.
    """
    inv = context.findings.get("inventory") or {}
    sup = context.findings.get("supplier") or {}
    ship = context.findings.get("shipment") or {}
    rep = context.findings.get("report") or {}

    # Build result string
    result_parts = []
    if inv.get("critical_count", 0) > 0:
        result_parts.append(f"{inv['critical_count']} critical inventory item(s)")
    if ship.get("high_risk_count", 0) > 0:
        result_parts.append(f"{ship['high_risk_count']} high-risk shipment(s)")
    if ship.get("cascade_count", 0) > 0:
        result_parts.append(f"{ship['cascade_count']} cascade risk(s)")
    if sup.get("best_supplier"):
        result_parts.append(f"Supplier: {sup['best_supplier']['name']}")

    result = (
        "Assessment complete — " + ", ".join(result_parts)
        if result_parts else
        "Assessment complete — all systems nominal"
    )

    return {
        "result": result,
        "issue": {
            "critical_inventory_items": inv.get("critical_count", 0),
            "high_risk_shipments": ship.get("high_risk_count", 0),
            "cascade_risks": ship.get("cascade_count", 0),
            "red_items": [i["product_name"] for i in context.critical_inventory_items if i.get("status") == "Red"],
            "yellow_items": [i["product_name"] for i in context.critical_inventory_items if i.get("status") == "Yellow"],
        },
        "recommendation": {
            "best_supplier": sup.get("best_supplier"),
            "report_actions": rep.get("recommendations", []),
            "high_risk_shipments": ship.get("high_risk_shipments", [])[:3],
            "critical_items": inv.get("critical_items", [])[:3],
        },
        "reasoning": synthesis,
        "context": (
            f"{inv.get('total_items', 0)} products | "
            f"{len(context.critical_inventory_items)} need attention | "
            f"{ship.get('cascade_count', 0)} cascade(s) | "
            f"Judge confidence: {judge_verdict.overall_confidence:.0%}"
        ),
        "kpis": rep.get("kpis"),
        "cascade_risk": "\n".join(context.cascade_risks[:3]) if context.cascade_risks else None,
        "carrier_flag": ship.get("carrier_flag"),
        "executive_summary": rep.get("executive_summary"),
        "root_causes": rep.get("root_causes", []),
        "forward_projections": rep.get("forward_projections", []),
        "trace": trace.dict(),
        "judge_verdict": judge_verdict.dict(),
    }


def _build_goal_description(action: str, params: Dict[str, Any]) -> str:
    """Human-readable goal for the trace."""
    goals = {
        "analyze_inventory": f"Analyze inventory health for product '{params.get('product_id', 'all')}'",
        "select_supplier": f"Select best supplier for {params.get('quantity', 100)} units (urgency: {params.get('urgency', 'normal')})",
        "track_shipment": f"Track and assess risk for shipment '{params.get('shipment_id', 'unknown')}'",
        "generate_report": "Generate executive KPI report for supply chain",
        "full_assessment": "Perform full autonomous supply chain risk assessment",
        "ask": f"Answer query: '{(params.get('query') or '')[:80]}'",
    }
    return goals.get(action, f"Execute action: {action}")
