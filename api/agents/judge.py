"""
JudgeAgent — the quality gate of the multi-agent system.

After all specialist agents finish, the Judge:
  1. Checks for contradictions between agent recommendations
  2. Validates reasonableness of individual recommendations
  3. Scores overall confidence of the combined output
  4. Returns warnings and improvement suggestions

Every call has a deterministic fallback — Judge failure never crashes the system.
"""

import os
import json
import re
import time
from typing import Any, Dict, List

from api.llm_client import acomplete_json
from api.agents.context import AgentContext, JudgeVerdict
from api.config import supplier_config


class JudgeAgent:
    """
    Validates the combined output of all specialist agents.
    Acts as an independent quality reviewer — it does not participate
    in the analysis itself, only in the validation.

    Think of it as a senior supply chain expert reviewing the junior
    analysts' (specialist agents') work before it goes to the manager.
    """

    async def validate(self, context: AgentContext) -> JudgeVerdict:
        """
        Main validation entry point. Called once after all agents complete.
        Returns a JudgeVerdict with confidence score, contradictions, and warnings.
        """
        t0 = time.time()

        # Run deterministic checks first (fast, no LLM)
        contradictions = self._check_contradictions(context)
        reasonableness_warnings = self._check_reasonableness(context)

        # Build a full picture for the LLM to evaluate
        agent_outputs = self._summarize_agent_outputs(context)

        # LLM validation for nuanced issues
        llm_verdict = await self._llm_validate(
            context=context,
            agent_outputs=agent_outputs,
            known_contradictions=contradictions,
            known_warnings=reasonableness_warnings,
        )

        # Merge deterministic + LLM findings
        all_contradictions = list(dict.fromkeys(contradictions + llm_verdict.get("contradictions", [])))
        all_warnings = list(dict.fromkeys(reasonableness_warnings + llm_verdict.get("warnings", [])))
        improvements = llm_verdict.get("improvements", [])

        # Compute final confidence
        confidence = self._compute_confidence(
            context=context,
            num_contradictions=len(all_contradictions),
            num_warnings=len(all_warnings),
            llm_confidence=llm_verdict.get("confidence", 0.7),
        )

        is_valid = len(all_contradictions) == 0 and confidence >= 0.5

        duration_ms = int((time.time() - t0) * 1000)

        # Record in context trace
        context.add_step(
            agent_name="judge",
            task="Validate consistency and quality of all agent outputs",
            finding=(
                f"Validation {'passed' if is_valid else 'failed'}. "
                f"Confidence: {confidence:.0%}. "
                f"{len(all_contradictions)} contradiction(s), {len(all_warnings)} warning(s)."
            ),
            data={
                "is_valid": is_valid,
                "confidence": confidence,
                "contradictions": all_contradictions,
                "warnings": all_warnings,
                "improvements": improvements,
            },
            confidence=confidence,
            duration_ms=duration_ms,
        )

        return JudgeVerdict(
            is_valid=is_valid,
            overall_confidence=round(confidence, 3),
            contradictions=all_contradictions,
            warnings=all_warnings,
            improvements=improvements,
            reasoning=llm_verdict.get("reasoning", ""),
        )

    # ── Deterministic Checks (no LLM, always run) ────────────────────────

    def _check_contradictions(self, context: AgentContext) -> List[str]:
        """
        Checks for logical contradictions between agent outputs.
        These are rule-based — no LLM needed for obvious inconsistencies.
        """
        contradictions = []

        inv_finding = context.findings.get("inventory")
        sup_finding = context.findings.get("supplier")
        ship_finding = context.findings.get("shipment")

        # Contradiction 1: Supplier used IMMEDIATE urgency but no inventory is critical AND no cascade risks exist
        # (Why order urgently if nothing is low and there are no upcoming cascades?)
        if sup_finding and inv_finding:
            urgency_used = sup_finding.get("urgency_used", "normal")
            critical_count = len(context.critical_inventory_items)
            cascade_count = len(context.cascade_risks)
            if urgency_used == "immediate" and critical_count == 0 and cascade_count == 0:
                contradictions.append(
                    "Supplier Agent used IMMEDIATE urgency but Inventory Agent found no critical items "
                    "and Shipment Agent found no cascade risks. Urgency level is miscalibrated."
                )

        # Contradiction 2: High cascade risk but no supplier recommendation
        if context.cascade_risks and not context.recommended_suppliers:
            contradictions.append(
                f"{len(context.cascade_risks)} cascade risk(s) detected but no supplier was "
                "recommended. The system should have triggered supplier selection for emergency reorder."
            )

        # (Removed Contradiction 3: It is perfectly normal for healthy inventory to have cascade risks due to future delays)

        # Contradiction 4: Recommended supplier is the one causing the delay!
        if sup_finding and ship_finding and context.recommended_suppliers:
            top_supplier_name = context.recommended_suppliers[0].get("name", "")
            delayed_suppliers = [
                s.get("supplier", "") for s in ship_finding.get("high_risk_shipments", [])
            ]
            if top_supplier_name and top_supplier_name in delayed_suppliers:
                contradictions.append(
                    f"Recommended supplier '{top_supplier_name}' has an active delayed shipment — "
                    "consider alternative carrier or emergency supplier."
                )

        return contradictions

    def _check_reasonableness(self, context: AgentContext) -> List[str]:
        """
        Sanity-checks individual agent outputs for obviously unreasonable values.
        Examples: ordering 100,000 units when daily consumption is 5,
                  a supplier with 0% on-time rate ranked #1.
        """
        warnings = []

        # Check supplier recommendation reasonableness
        if context.recommended_suppliers:
            top = context.recommended_suppliers[0]
            on_time = top.get("on_time_delivery_rate", 1.0)
            if on_time < supplier_config.low_reliability_threshold:
                warnings.append(
                    f"Recommended supplier '{top.get('name', '?')}' has only "
                    f"{on_time:.0%} on-time delivery rate. Consider this carefully."
                )

        # Check inventory reorder quantities
        for item in context.critical_inventory_items:
            eoq = item.get("eoq", 0)
            avg_daily = item.get("avg_daily_consumption", 1)
            if avg_daily and avg_daily > 0 and eoq > 0:
                days_of_supply = eoq / avg_daily
                if days_of_supply > 365:
                    warnings.append(
                        f"EOQ for '{item.get('product_name', '?')}' is {eoq} units "
                        f"({days_of_supply:.0f} days of supply). This seems excessive — "
                        "verify ordering cost and holding cost inputs."
                    )

        # Check cascade risk coverage
        if context.cascade_risks:
            warnings.append(
                "Weather impact in delay calculation is a fixed estimate (0.5 days), "
                "not live weather data. Actual delays may vary."
            )

        return warnings

    def _compute_confidence(
        self,
        context: AgentContext,
        num_contradictions: int,
        num_warnings: int,
        llm_confidence: float,
    ) -> float:
        """
        Compute final confidence score by combining:
        - LLM's assessed confidence
        - Penalty for contradictions (-0.15 each)
        - Penalty for warnings (-0.05 each)
        - Bonus for more agents completing (+0.03 each)
        """
        base = llm_confidence
        base -= num_contradictions * 0.15
        base -= num_warnings * 0.05

        # Bonus for multi-agent coverage
        completed_agents = sum(
            1 for v in context.findings.values() if v is not None
        )
        base += completed_agents * 0.03

        return round(min(max(base, 0.1), 0.97), 3)

    # ── LLM Validation ────────────────────────────────────────────────────

    async def _llm_validate(
        self,
        context: AgentContext,
        agent_outputs: str,
        known_contradictions: List[str],
        known_warnings: List[str],
    ) -> Dict[str, Any]:
        """
        Uses the Groq LLM to perform nuanced validation that deterministic rules miss.
        Has a complete deterministic fallback.
        """
        cascade_info = "\n".join(context.cascade_risks) if context.cascade_risks else "None"
        known_issues_text = ""
        if known_contradictions:
            known_issues_text += f"\nAlready detected contradictions:\n" + "\n".join(f"- {c}" for c in known_contradictions)
        if known_warnings:
            known_issues_text += f"\nAlready detected warnings:\n" + "\n".join(f"- {w}" for w in known_warnings)

        prompt = f"""You are the Judge Agent — a senior supply chain expert reviewing the work of junior AI analysts.

AGENT OUTPUTS SUMMARY:
{agent_outputs}

CASCADE RISKS DETECTED:
{cascade_info}

{known_issues_text}

Evaluate the quality and consistency of these agent recommendations.
Look for:
1. Logical contradictions not yet listed above
2. Missing analysis (e.g., agents that should have run but didn't)
3. Improvements that would make the recommendations more actionable
4. Your overall confidence in these recommendations (0.0 to 1.0)

IMPORTANT RULES FOR YOUR VALIDATION:
- Do NOT flag it as a contradiction or warning if the Inventory Agent found fewer critical items than the Shipment Agent's cascade risks, or if it didn't list an item that later triggers a cascade risk. The Inventory Agent analyzes current static stock, while the Shipment Agent projects future stock.
- Do NOT flag it as a contradiction if the Supplier Agent only recommends one supplier. The system is designed to output only the single mathematically best supplier.
- Do NOT flag it as a contradiction or warning if Inventory Health KPI is high (e.g., 97-100%) while Cascade Risks (or projected stockouts) exist. Inventory Health measures current stock, whereas Cascade Risks are future projections. This is perfectly consistent.
- Do NOT flag it as a contradiction or warning if the projected stock reduction in a cascade risk doesn't seem to perfectly match the shipment quantity. The Shipment Agent uses dynamic daily demand rates that you do not have access to.
- Do NOT flag it as a contradiction if the Supplier Agent's recommended order quantity differs from the Inventory Agent's reported on-hand stock quantity. These are two completely different metrics.
- Do NOT flag it as a contradiction or consistency gap if the Supervisor adapts the plan mid-execution (e.g., "Plan adapted: supplier_agent -> report_agent"). An adapted plan only lists the *remaining* steps; the prior agents (like inventory and shipment) already successfully ran and their data is still fresh and valid in the current cycle.
- CRITICAL: Do NOT hallucinate data! Only cite numbers that are explicitly written in the agent outputs. If the Inventory Agent did not explicitly state a specific stock quantity for a specific SKU, do not invent one (like "100 units") just to create a contradiction.
- Do NOT flag it as a warning or error if there are multiple cascade risks for the same SKU. This simply means that multiple different incoming shipments for that SKU have been delayed, creating distinct points of failure.

Respond ONLY in valid JSON:
{{
  "confidence": 0.85,
  "contradictions": ["list any new contradictions not already listed"],
  "warnings": ["list any new warnings not already listed"],
  "improvements": ["concrete suggestions to improve the analysis"],
  "reasoning": "2-3 sentence overall assessment of the recommendation quality"
}}
"""
        try:
            return await acomplete_json(
                prompt,
                fallback={
                    "confidence": 0.6,
                    "contradictions": [],
                    "warnings": ["Judge LLM validation unavailable — confidence score is estimated"],
                    "improvements": ["Re-run assessment when LLM service is available for full validation"],
                    "reasoning": "Automated validation only. Manual review recommended for critical decisions.",
                },
            )

        except Exception as e:
            print(f"[JUDGE] LLM validation failed ({e}), using deterministic fallback")
            num_agents = sum(1 for v in context.findings.values() if v is not None)
            base_confidence = 0.5 + (num_agents * 0.08)
            return {
                "confidence": round(min(base_confidence, 0.75), 2),
                "contradictions": [],
                "warnings": ["Judge LLM validation unavailable — confidence score is estimated"],
                "improvements": ["Re-run assessment when LLM service is available for full validation"],
                "reasoning": (
                    f"Automated validation only. {num_agents} agent(s) completed. "
                    "Manual review recommended for critical decisions."
                ),
            }

    # ── Helpers ───────────────────────────────────────────────────────────

    def _summarize_agent_outputs(self, context: AgentContext) -> str:
        """Formats all agent step findings for the LLM prompt."""
        lines = []
        for step in context._steps:
            if step.agent_name in ("judge",):
                continue
            lines.append(
                f"[{step.agent_name.upper()}] Task: {step.task}\n"
                f"  Finding: {step.finding}\n"
                f"  Confidence: {step.confidence:.0%}"
            )
        return "\n\n".join(lines) if lines else "No agent outputs available."
