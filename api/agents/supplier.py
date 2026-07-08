from pydantic import BaseModel
from typing import List, Optional
import math

from api.llm_client import acomplete


class SupplierProfile(BaseModel):
    name: str
    base_cost_per_unit: float
    on_time_delivery_rate: float  # 0.0 to 1.0
    lead_time_days: int
    quality_rating: float         # 1.0 to 5.0
    historical_issues: int
    contact_info: Optional[str] = None


class SupplierScore(BaseModel):
    name: str
    total_cost: float
    risk_score: float
    final_score: float
    recommendation_rank: int
    reasoning: str
    strengths: List[str]
    weaknesses: List[str]


class SupplierAgent:
    def __init__(self):
        # Base weights
        self.base_weights = {
            "cost":        0.30,
            "reliability": 0.35,
            "speed":       0.20,
            "quality":     0.15
        }
        self.urgency_premium = 0.15  # 15% cost markup for rush orders

    def get_dynamic_weights(self, is_urgent: bool, quantity: int) -> dict:
        """
        Dynamically adjusts weights based on context:
        - Urgent order: speed matters more, cost matters less
        - Large order: reliability and quality matter more
        """
        weights = self.base_weights.copy()

        if is_urgent:
            weights["speed"]       += 0.15
            weights["cost"]        -= 0.10
            weights["reliability"] += 0.05
            weights["quality"]     -= 0.10

        if quantity > 500:
            weights["reliability"] += 0.05
            weights["quality"]     += 0.05
            weights["cost"]        -= 0.10

        # Normalize so weights always sum to 1.0
        total = sum(weights.values())
        return {k: round(v / total, 3) for k, v in weights.items()}

    def calculate_true_cost(
        self,
        profile: SupplierProfile,
        quantity: int,
        is_urgent: bool
    ) -> float:
        """
        True Cost = Base Cost
                  + Urgency Premium (15% for rush)
                  + Carrying Cost (2% per lead time day)
                  + Risk Penalty (historical issues × 2% of base)
        """
        base          = profile.base_cost_per_unit * quantity
        urgency_fee   = (base * self.urgency_premium) if is_urgent else 0
        carrying_cost = base * (profile.lead_time_days * 0.02)
        risk_penalty  = base * (profile.historical_issues * 0.02)
        return round(base + urgency_fee + carrying_cost + risk_penalty, 2)

    def calculate_risk_score(self, profile: SupplierProfile) -> float:
        """
        Risk Score = (1 - on_time_rate) × 0.5
                   + (1 - quality/5)    × 0.3
                   + historical_issues  × 0.2
        Lower is better.
        """
        risk = (
            ((1 - profile.on_time_delivery_rate) * 0.5) +
            ((1 - (profile.quality_rating / 5))  * 0.3) +
            (profile.historical_issues            * 0.2)
        )
        return round(min(risk, 1.0), 3)

    def get_strengths_weaknesses(
        self,
        profile: SupplierProfile,
        is_urgent: bool
    ) -> tuple[List[str], List[str]]:
        strengths  = []
        weaknesses = []

        if profile.on_time_delivery_rate >= 0.95:
            strengths.append(f"Excellent on-time rate ({profile.on_time_delivery_rate*100:.0f}%)")
        elif profile.on_time_delivery_rate < 0.80:
            weaknesses.append(f"Poor on-time rate ({profile.on_time_delivery_rate*100:.0f}%)")

        if profile.quality_rating >= 4.5:
            strengths.append(f"High quality rating ({profile.quality_rating}/5)")
        elif profile.quality_rating < 3.5:
            weaknesses.append(f"Low quality rating ({profile.quality_rating}/5)")

        if profile.lead_time_days <= 4:
            strengths.append(f"Fast lead time ({profile.lead_time_days} days)")
        elif profile.lead_time_days >= 10:
            weaknesses.append(f"Slow lead time ({profile.lead_time_days} days)")
            if is_urgent:
                weaknesses.append("Not suitable for urgent orders")

        if profile.historical_issues == 0:
            strengths.append("No historical issues")
        elif profile.historical_issues >= 2:
            weaknesses.append(f"{profile.historical_issues} past incidents on record")

        return strengths, weaknesses

    async def select_best_supplier(
        self,
        suppliers: List[SupplierProfile],
        quantity: int,
        is_urgent: bool
    ) -> List[SupplierScore]:

        if not suppliers:
            return []

        weights = self.get_dynamic_weights(is_urgent, quantity)

        # Pre-calculate costs for normalization
        costs   = [self.calculate_true_cost(s, quantity, is_urgent) for s in suppliers]
        max_cost = max(costs) if costs else 1

        scored_list = []
        for i, profile in enumerate(suppliers):
            true_cost = costs[i]
            risk      = self.calculate_risk_score(profile)

            # Normalize each dimension to 0-1 (higher = better)
            cost_score    = 1 - (true_cost / (max_cost * 1.2))
            speed_score   = min((1 / profile.lead_time_days) * 5, 1.0)
            quality_score = profile.quality_rating / 5

            final_score = round(
                (cost_score                       * weights["cost"])        +
                (profile.on_time_delivery_rate    * weights["reliability"]) +
                (speed_score                      * weights["speed"])       +
                (quality_score                    * weights["quality"]),
                4
            )

            strengths, weaknesses = self.get_strengths_weaknesses(profile, is_urgent)

            reasoning = (
                f"Weights applied — Cost: {weights['cost']:.0%}, "
                f"Reliability: {weights['reliability']:.0%}, "
                f"Speed: {weights['speed']:.0%}, "
                f"Quality: {weights['quality']:.0%}. "
                f"True cost ${true_cost:,.2f} includes lead time carrying costs"
                f"{' and urgency premium' if is_urgent else ''}. "
                f"Risk score: {risk:.2f}/1.0."
            )

            scored_list.append(SupplierScore(
                name=profile.name,
                total_cost=true_cost,
                risk_score=risk,
                final_score=final_score,
                recommendation_rank=0,
                reasoning=reasoning,
                strengths=strengths,
                weaknesses=weaknesses
            ))

        # Sort by final score descending
        scored_list.sort(key=lambda x: x.final_score, reverse=True)
        for idx, score in enumerate(scored_list):
            score.recommendation_rank = idx + 1

        return scored_list

    async def generate_contextual_reasoning(
        self,
        best: "SupplierScore",
        all_scores: List["SupplierScore"],
        cross_agent_context: str = "",
    ) -> str:
        """
        T2.1 — LLM-powered contextual reasoning that explains WHY this supplier
        was chosen, referencing cross-agent findings (inventory urgency, cascade risks).
        Falls back to deterministic summary if LLM fails.
        """
        runner_up = all_scores[1] if len(all_scores) > 1 else None
        runner_up_text = (
            f"Runner-up: {runner_up.name} (score {runner_up.final_score:.3f}, "
            f"${runner_up.total_cost:,.0f}, risk {runner_up.risk_score:.2f})."
            if runner_up else "No runner-up available."
        )

        prompt = f"""You are a supply chain specialist explaining a supplier selection decision.

RECOMMENDED SUPPLIER: {best.name}
  Score:       {best.final_score:.3f}
  Total Cost:  ${best.total_cost:,.2f}
  Risk Score:  {best.risk_score:.2f}
  Strengths:   {', '.join(best.strengths) or 'None noted'}
  Weaknesses:  {', '.join(best.weaknesses) or 'None noted'}

{runner_up_text}

CROSS-AGENT CONTEXT (inventory + shipment findings):
{cross_agent_context or 'No cross-agent context available.'}

Formulaics reasoning already computed: {best.reasoning}

Write 2 concise sentences explaining the recommendation:
1. Why THIS supplier over alternatives, citing the most decisive metric.
2. How inventory or shipment findings (from context above) influenced the choice.
Be specific with numbers. Do not use bullet points.
"""
        try:
            return await acomplete(prompt, temperature=0.2, max_tokens=200)
        except Exception:
            parts = [f"{best.name} selected with score {best.final_score:.3f}."]
            if best.strengths:
                parts.append(f"Key strengths: {', '.join(best.strengths[:2])}.")
            if cross_agent_context:
                parts.append("Selection informed by cross-agent inventory and shipment findings.")
            return " ".join(parts)