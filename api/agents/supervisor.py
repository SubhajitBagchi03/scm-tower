"""
SupervisorAgent — the brain of the multi-agent system.

Responsibilities:
  1. create_plan()      — Decomposes the goal into an ordered list of agent tasks (LLM-powered)
  2. should_adapt()     — Mid-execution: checks if findings warrant changing the plan
  3. synthesize()       — After all agents run: produces a consolidated recommendation (LLM-powered)

Every LLM call has a deterministic fallback so an LLM failure never crashes the system.
"""

import os
import json
import time
import re
from typing import Any, Dict, List, Optional

from api.llm_client import acomplete_json, acomplete
from api.agents.context import AgentContext, PlanStep, SupervisorPlan

# ─────────────────────────────────────────────
# AGENT REGISTRY
# ─────────────────────────────────────────────

AVAILABLE_AGENTS = {
    "inventory_agent": (
        "Analyzes inventory health. Calculates EOQ, safety stock, reorder points, "
        "days until stockout. Identifies critical (Red) and warning (Yellow) items. "
        "Use this first — its findings drive urgency for supplier and shipment agents."
    ),
    "supplier_agent": (
        "Selects the best supplier using weighted scoring (cost, reliability, speed, quality). "
        "Weights shift dynamically based on urgency. Use after inventory_agent when "
        "reorder decisions need to be made."
    ),
    "shipment_agent": (
        "Assesses shipment delay risk and detects cascade risks "
        "(delayed shipment + low inventory = stockout). "
        "Use to check if incoming shipments cover critical inventory gaps."
    ),
    "report_agent": (
        "Calculates KPIs and generates an executive summary. "
        "Always use last — it needs full context from all prior agents to produce "
        "a meaningful integrated report."
    ),
}

# Fixed plan templates — used as fallback when LLM is unavailable
FALLBACK_PLANS: Dict[str, SupervisorPlan] = {
    "analyze_inventory": SupervisorPlan(
        reasoning="Single-product inventory analysis: check stock, then validate supplier context.",
        steps=[
            PlanStep(agent="inventory_agent", task="Analyze the specific product's stock health, EOQ, and reorder urgency", depends_on=[]),
            PlanStep(agent="supplier_agent", task="Identify best supplier for reorder if product is critical", depends_on=[0]),
        ]
    ),
    "select_supplier": SupervisorPlan(
        reasoning="Supplier selection: check inventory urgency first to calibrate weights, then score suppliers.",
        steps=[
            PlanStep(agent="inventory_agent", task="Identify any critical inventory items to determine urgency level", depends_on=[]),
            PlanStep(agent="supplier_agent", task="Score and rank all suppliers with urgency context from inventory findings", depends_on=[0]),
        ]
    ),
    "track_shipment": SupervisorPlan(
        reasoning="Shipment tracking: check inventory first to enable cascade detection, then track shipment.",
        steps=[
            PlanStep(agent="inventory_agent", task="Scan all inventory to identify products at risk of stockout", depends_on=[]),
            PlanStep(agent="shipment_agent", task="Analyze the shipment delay risk and cascade impact on critical inventory items", depends_on=[0]),
        ]
    ),
    "full_assessment": SupervisorPlan(
        reasoning="Full supply chain assessment: inventory first (establishes urgency), then shipments (cascade detection), then suppliers (informed by urgency and cascades), finally report (integrated synthesis).",
        steps=[
            PlanStep(agent="inventory_agent", task="Scan all inventory — identify critical and warning items", depends_on=[]),
            PlanStep(agent="shipment_agent", task="Check all shipments for delay risk, prioritizing cascade detection for critical inventory items", depends_on=[0]),
            PlanStep(agent="supplier_agent", task="Select best supplier(s) for critical items, with urgency elevated if cascades were detected", depends_on=[0, 1]),
            PlanStep(agent="report_agent", task="Generate executive KPI report using full context from all prior agents", depends_on=[0, 1, 2]),
        ]
    ),
    "ask": SupervisorPlan(
        reasoning="Natural language query: route to the appropriate data source.",
        steps=[
            PlanStep(agent="inventory_agent", task="Answer the question using live supply chain data", depends_on=[]),
        ]
    ),
    "generate_report": SupervisorPlan(
        reasoning="Executive report: scan all data domains then synthesize.",
        steps=[
            PlanStep(agent="inventory_agent", task="Scan inventory for KPIs and critical items", depends_on=[]),
            PlanStep(agent="shipment_agent", task="Assess shipment performance and cascade risks", depends_on=[0]),
            PlanStep(agent="supplier_agent", task="Evaluate supplier health scores", depends_on=[0]),
            PlanStep(agent="report_agent", task="Generate integrated executive report with all findings", depends_on=[0, 1, 2]),
        ]
    ),
}


class SupervisorAgent:
    """
    Plans, routes, and synthesizes the multi-agent workflow.
    The Supervisor never executes domain logic itself — it only coordinates.
    """

    # ── Plan Creation ─────────────────────────────────────────────────────

    async def create_plan(
        self,
        action: str,
        params: Dict[str, Any],
        data_summary: str,
    ) -> SupervisorPlan:
        """
        Uses the Groq LLM to decompose the goal into an ordered execution plan.
        Falls back to a hardcoded plan if the LLM fails.

        data_summary: brief description of what data is available
                      (e.g., "25 inventory items, 5 suppliers, 10 shipments")
        """
        prompt = f"""You are the Supervisor of a supply chain AI system.
Your job is to create an execution plan for the following action.

ACTION: {action}
PARAMETERS: {json.dumps(params, default=str)}
AVAILABLE DATA: {data_summary}

AVAILABLE AGENTS:
{self._format_agents()}

Create a step-by-step plan. Rules:
1. Order agents so each one has the context it needs from prior agents
2. For full_assessment: always order inventory → shipment → supplier → report
3. For single-agent actions: still consider adding a supporting agent if it helps
4. Keep plans short (2-4 steps max)

Respond ONLY in valid JSON, no markdown, no explanation:
{{
  "reasoning": "why this plan order was chosen",
  "steps": [
    {{"agent": "agent_name", "task": "specific task description", "depends_on": []}},
    {{"agent": "agent_name", "task": "specific task description", "depends_on": [0]}}
  ]
}}
"""
        try:
            parsed = await acomplete_json(
                prompt,
                fallback={"reasoning": "fallback", "steps": []},
            )

            steps = [
                PlanStep(
                    agent=s["agent"],
                    task=s["task"],
                    depends_on=s.get("depends_on", []),
                )
                for s in parsed.get("steps", [])
                if s.get("agent") in AVAILABLE_AGENTS
            ]

            if not steps:
                raise ValueError("No valid steps returned")

            return SupervisorPlan(reasoning=parsed.get("reasoning", "LLM plan"), steps=steps)

        except Exception as e:
            print(f"[SUPERVISOR] Plan LLM failed ({e}), using fallback plan for '{action}'")
            return FALLBACK_PLANS.get(action, FALLBACK_PLANS["full_assessment"])

    # ── Plan Adaptation ────────────────────────────────────────────────────

    async def should_adapt_plan(
        self,
        context: AgentContext,
        remaining_steps: List[PlanStep],
    ) -> Optional[List[PlanStep]]:
        """
        Called after each agent completes. Checks if new findings warrant
        changing the remaining plan.

        Returns a new list of steps if the plan should change, None if it's fine.
        This is what makes the system truly adaptive — it can re-plan mid-run.
        """
        findings_summary = context.get_findings_summary()

        # Fast-path: if no critical findings, don't call the LLM
        if not context.critical_inventory_items and not context.cascade_risks:
            return None

        if not remaining_steps:
            return None

        prompt = f"""You are the Supervisor of a supply chain AI system.
You are mid-execution. Review the findings so far and decide if the remaining plan needs to change.

FINDINGS SO FAR:
{findings_summary}

CASCADE RISKS DETECTED: {len(context.cascade_risks)}
CRITICAL INVENTORY ITEMS: {len(context.critical_inventory_items)}

REMAINING PLAN STEPS:
{json.dumps([{"agent": s.agent, "task": s.task} for s in remaining_steps], indent=2)}

AVAILABLE AGENTS: {list(AVAILABLE_AGENTS.keys())}

- If "CASCADE RISKS DETECTED" > 0 AND the Supplier Agent has NOT run yet (check FINDINGS SO FAR to see if [SUPPLIER] exists), you MUST return adapt: true.
- When adapting, your "updated_steps" array MUST include ALL of the existing REMAINING PLAN STEPS, plus the newly added "supplier_agent" placed before "report_agent".
- CRITICAL: If [SUPPLIER] is already in the FINDINGS SO FAR, you MUST return adapt: false because the emergency supplier has already been found. Do not loop!

Respond ONLY in valid JSON:
{{
  "adapt": true or false,
  "reason": "why adaptation is needed or not",
  "updated_steps": [
    {{"agent": "agent_name", "task": "updated task", "depends_on": []}}
  ]
}}
"""
        try:
            parsed = await acomplete_json(
                prompt,
                fallback={"adapt": False, "updated_steps": []},
            )

            if not parsed.get("adapt", False):
                return None

            updated = [
                PlanStep(
                    agent=s["agent"],
                    task=s["task"],
                    depends_on=s.get("depends_on", []),
                )
                for s in parsed.get("updated_steps", [])
                if s.get("agent") in AVAILABLE_AGENTS
            ]
            return updated if updated else None

        except Exception:
            return None

    # ── Synthesis ───────────────────────────────────────────────────────────

    async def synthesize(self, context: AgentContext) -> str:
        """
        After all agents have run, produce a consolidated final recommendation.
        This is the Supervisor's most important output — it integrates everything.
        """
        findings_summary = context.get_findings_summary()

        cascade_text = "\n".join(context.cascade_risks) if context.cascade_risks else "None detected"
        critical_text = (
            ", ".join(i.get("product_name", "?") for i in context.critical_inventory_items[:5])
            if context.critical_inventory_items else "None"
        )
        supplier_text = (
            f"{context.recommended_suppliers[0].get('name', '?')} "
            f"(score: {context.recommended_suppliers[0].get('final_score', '?')})"
            if context.recommended_suppliers else "No recommendation made"
        )

        prompt = f"""You are the Supervisor of a supply chain AI system.
All specialist agents have completed their analysis. Synthesize their findings into ONE clear, actionable recommendation for the supply chain manager.

AGENT FINDINGS:
{findings_summary}

CASCADE RISKS:
{cascade_text}

CRITICAL INVENTORY ITEMS:
{critical_text}

BEST SUPPLIER RECOMMENDATION:
{supplier_text}

Write a 2-4 sentence synthesis that:
1. States the most critical finding (what needs immediate attention)
2. Explains the cross-agent connection (e.g., why the shipment delay makes the inventory situation worse)
3. Gives a specific, actionable recommendation (what to do, with which supplier, by when)
4. Notes any important caveats

Be direct and specific. Use numbers when you have them. Do not use bullet points — write in flowing sentences.
"""
        try:
            return await acomplete(prompt)
        except Exception as e:
            # Deterministic fallback
            parts = []
            if context.critical_inventory_items:
                names = [i.get("product_name", "?") for i in context.critical_inventory_items[:3]]
                parts.append(f"{len(context.critical_inventory_items)} items need attention: {', '.join(names)}.")
            if context.cascade_risks:
                parts.append(f"{len(context.cascade_risks)} cascade risk(s) detected — immediate action required.")
            if context.recommended_suppliers:
                top = context.recommended_suppliers[0]
                parts.append(f"Recommended supplier: {top.get('name', '?')}.")
            if not parts:
                parts.append("Assessment complete. Review agent findings for details.")
            return " ".join(parts)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _format_agents(self) -> str:
        return "\n".join(
            f"- {name}: {desc}" for name, desc in AVAILABLE_AGENTS.items()
        )
