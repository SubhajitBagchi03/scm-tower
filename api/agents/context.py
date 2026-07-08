"""
AgentContext — shared memory layer for the multi-agent system.

Every agent run creates one AgentContext. It is passed between agents so
each agent can see what previous agents found. This is what makes the
system truly agentic: Supplier Agent knows what Inventory Agent found,
Shipment Agent knows what both found, etc.
"""

import uuid
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


# ─────────────────────────────────────────────
# PYDANTIC MODELS (serializable for API response)
# ─────────────────────────────────────────────

class PlanStep(BaseModel):
    """A single step in the Supervisor's execution plan."""
    agent: str           # "inventory_agent" | "supplier_agent" | "shipment_agent" | "report_agent"
    task: str            # Human-readable description of what this agent must do
    depends_on: List[int] = []  # Indices of steps this step depends on (for context)


class SupervisorPlan(BaseModel):
    """The Supervisor's structured plan for achieving the goal."""
    reasoning: str       # Why this plan was chosen (LLM-generated)
    steps: List[PlanStep]


class AgentStep(BaseModel):
    """Record of one agent's execution — persisted in the trace."""
    step_index: int
    agent_name: str      # "supervisor" | "inventory_agent" | etc.
    task: str
    finding: str         # One-line human-readable finding
    data: Dict[str, Any] = {}   # Structured output from this agent
    confidence: float = 0.5     # 0.0 to 1.0
    duration_ms: int = 0
    timestamp: str = ""


class JudgeVerdict(BaseModel):
    """Quality gate: Judge Agent's validation of all agent outputs."""
    is_valid: bool
    overall_confidence: float       # 0.0 to 1.0
    contradictions: List[str] = []  # Detected contradictions between agents
    warnings: List[str] = []        # Non-critical issues
    improvements: List[str] = []    # Suggestions for better analysis
    reasoning: str = ""             # Full explanation


class AgentTrace(BaseModel):
    """Complete execution trace for one agent run — returned in API response."""
    run_id: str
    goal: str
    action: str
    plan: Optional[SupervisorPlan] = None
    steps: List[AgentStep] = []
    judge_verdict: Optional[JudgeVerdict] = None
    synthesis: str = ""
    total_duration_ms: int = 0
    timestamp: str = ""


# ─────────────────────────────────────────────
# AGENT CONTEXT (mutable, passed between agents)
# ─────────────────────────────────────────────

class AgentContext:
    """
    Shared memory passed between all agents in a single run.

    Agents READ from this to understand what previous agents found.
    Agents WRITE to this when they complete their step.

    This is what enables cross-agent reasoning — the Supplier Agent
    can reference the Inventory Agent's critical items, and the
    Shipment Agent can reference both.
    """

    def __init__(self, goal: str, action: str, params: Dict[str, Any]):
        self.run_id = str(uuid.uuid4())
        self.goal = goal
        self.action = action
        self.params = params
        self.plan: Optional[SupervisorPlan] = None
        self._steps: List[AgentStep] = []
        self._start_time = time.time()

        # Cross-agent findings — agents write here for others to read
        self.findings: Dict[str, Any] = {
            "inventory": None,    # Set by inventory_agent
            "supplier": None,     # Set by supplier_agent
            "shipment": None,     # Set by shipment_agent
            "report": None,       # Set by report_agent
        }

        # Critical items discovered mid-run (drives plan adaptation)
        self.critical_inventory_items: List[Dict] = []
        self.high_risk_shipments: List[Dict] = []
        self.cascade_risks: List[str] = []
        self.recommended_suppliers: List[Dict] = []

    # ── Plan ────────────────────────────────

    def set_plan(self, plan: SupervisorPlan) -> None:
        self.plan = plan

    # ── Step Recording ───────────────────────

    def add_step(
        self,
        agent_name: str,
        task: str,
        finding: str,
        data: Dict[str, Any],
        confidence: float = 0.7,
        duration_ms: int = 0,
    ) -> AgentStep:
        """Record a completed agent step and store it in the trace."""
        step = AgentStep(
            step_index=len(self._steps),
            agent_name=agent_name,
            task=task,
            finding=finding,
            data=data,
            confidence=round(confidence, 3),
            duration_ms=duration_ms,
            timestamp=datetime.utcnow().isoformat(),
        )
        self._steps.append(step)
        return step

    # ── Cross-Agent Context (what agents read from each other) ───────────

    def get_findings_summary(self) -> str:
        """
        Returns a plain-text summary of all completed agent findings.
        The Supervisor uses this to decide whether to adapt the plan.
        New agents use this to understand the full picture so far.
        """
        if not self._steps:
            return "No agents have run yet."

        lines = []
        for step in self._steps:
            if step.agent_name in ("supervisor", "judge"):
                continue  # Don't include meta-agents in the summary
            lines.append(f"- [{step.agent_name.upper()}]: {step.finding}")

        # Include structured highlights
        if self.critical_inventory_items:
            names = [i.get("product_name", "?") for i in self.critical_inventory_items[:5]]
            lines.append(f"- [CRITICAL ITEMS]: {', '.join(names)}")

        if self.high_risk_shipments:
            ids = [s.get("shipment_id", "?") for s in self.high_risk_shipments[:3]]
            lines.append(f"- [HIGH RISK SHIPMENTS]: {', '.join(ids)}")

        if self.cascade_risks:
            lines.append(f"- [CASCADE RISKS DETECTED]: {len(self.cascade_risks)} cascade(s)")

        if self.recommended_suppliers:
            top = self.recommended_suppliers[0]
            lines.append(f"- [BEST SUPPLIER]: {top.get('name', '?')} (rank 1)")

        return "\n".join(lines) if lines else "No significant findings yet."

    def get_cross_agent_context_for(self, requesting_agent: str) -> str:
        """
        Returns a tailored context string for a specific agent.
        Each agent gets the most relevant subset of prior findings.

        This is the key mechanism that enables cross-agent reasoning:
        - Supplier Agent learns which products are critical → sizes the order correctly
        - Shipment Agent learns which items are at risk → prioritizes cascade checks
        - Report Agent learns everything → produces an integrated summary
        """
        lines = [f"Context for {requesting_agent} (findings from prior agents):"]

        if requesting_agent == "supplier_agent":
            # Supplier needs to know: which products are critical, with what urgency
            if self.critical_inventory_items:
                lines.append("\nCRITICAL INVENTORY ITEMS requiring reorder:")
                for item in self.critical_inventory_items[:5]:
                    lines.append(
                        f"  - {item.get('product_name')} | "
                        f"Stock: {item.get('quantity_in_stock')} | "
                        f"Status: {item.get('status')} | "
                        f"EOQ: {item.get('eoq', 'unknown')} units"
                    )
            if self.cascade_risks:
                lines.append("\nCASCADE RISKS (shipment delays affecting stock):")
                for risk in self.cascade_risks[:3]:
                    lines.append(f"  - {risk}")
                lines.append("  → These require IMMEDIATE urgency for supplier selection.")
            if not self.critical_inventory_items and not self.cascade_risks:
                lines.append("No critical inventory items detected. Standard urgency applies.")

        elif requesting_agent == "shipment_agent":
            # Shipment agent needs to know: which products to prioritize cascade checks for
            if self.critical_inventory_items:
                product_ids = [i.get("product_id", "") for i in self.critical_inventory_items]
                names = [i.get("product_name", "") for i in self.critical_inventory_items]
                lines.append(f"\nPriority products from Inventory Agent (check these for cascade risk):")
                for pid, name in zip(product_ids[:5], names[:5]):
                    lines.append(f"  - {name} (ID: {pid})")
            else:
                lines.append("No critical inventory items — run standard shipment risk assessment.")

        elif requesting_agent == "report_agent":
            # Report agent gets full picture
            lines.append(self.get_findings_summary())
            if self.cascade_risks:
                lines.append(f"\nCASCADE RISKS ({len(self.cascade_risks)} detected):")
                for r in self.cascade_risks:
                    lines.append(f"  - {r}")

        elif requesting_agent == "inventory_agent":
            # Inventory agent runs first usually, but if second pass, give shipment context
            if self.high_risk_shipments:
                lines.append("\nHIGH RISK SHIPMENTS (may affect inventory projections):")
                for s in self.high_risk_shipments[:3]:
                    lines.append(
                        f"  - {s.get('shipment_id')} | "
                        f"Cascade: {s.get('cascade', 'None')}"
                    )

        else:
            lines.append(self.get_findings_summary())

        return "\n".join(lines)

    # ── Trace Output ─────────────────────────

    def to_trace(self, synthesis: str, judge_verdict: Optional[JudgeVerdict] = None) -> AgentTrace:
        """Build the final AgentTrace to include in the API response."""
        total_ms = int((time.time() - self._start_time) * 1000)
        return AgentTrace(
            run_id=self.run_id,
            goal=self.goal,
            action=self.action,
            plan=self.plan,
            steps=list(self._steps),
            judge_verdict=judge_verdict,
            synthesis=synthesis,
            total_duration_ms=total_ms,
            timestamp=datetime.utcnow().isoformat(),
        )
