"""
api/config.py — Centralised configurable business rules (T4.3)

All threshold values that were previously hardcoded inside agents now
live here.  Agents read from this module instead of magic numbers,
making the system customisable per business without code changes.

Priority:  environment variable  >  config.json  >  default below
"""

import os
import json
from dataclasses import dataclass, field
from typing import Dict

# ── Optional override file ─────────────────────────────────────
_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config.json")


def _load_json() -> dict:
    """Load config.json if present, else return empty dict."""
    try:
        with open(_CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_json = _load_json()


def _get(key: str, default):
    """Resolve: env var > config.json > default."""
    env_val = os.getenv(key.upper())
    if env_val is not None:
        try:
            return type(default)(env_val)
        except (ValueError, TypeError):
            return env_val
    return _json.get(key, default)


# ── Inventory thresholds ───────────────────────────────────────

@dataclass
class InventoryConfig:
    # z-score for safety stock calculation (1.645 = 95% service level)
    service_level_z_score: float = field(
        default_factory=lambda: float(_get("service_level_z_score", 1.645))
    )
    # Fixed ordering cost per purchase order (USD)
    ordering_cost: float = field(
        default_factory=lambda: float(_get("ordering_cost", 50.0))
    )
    # Annual holding cost per unit (USD)
    holding_cost: float = field(
        default_factory=lambda: float(_get("holding_cost", 5.0))
    )
    # Demand std-dev estimate (days) — used when real std-dev not available
    demand_std_dev_days: float = field(
        default_factory=lambda: float(_get("demand_std_dev_days", 2.0))
    )
    # Seasonal demand multipliers per month (1=Jan … 12=Dec)
    seasonal_pattern: Dict[int, float] = field(default_factory=lambda: {
        1: 0.9, 2: 0.9, 3: 0.9,   # Q1 — slow
        4: 1.0, 5: 1.0, 6: 1.0,   # Q2 — normal
        7: 1.0, 8: 1.0, 9: 1.0,   # Q3 — normal
        10: 1.4, 11: 1.4, 12: 1.4  # Q4 — peak
    })


# ── Supplier scoring weights ───────────────────────────────────

@dataclass
class SupplierConfig:
    # Weights used under normal conditions (must sum to 1.0)
    normal_weights: Dict[str, float] = field(default_factory=lambda: {
        "cost":        float(_get("supplier_weight_cost",        0.30)),
        "reliability": float(_get("supplier_weight_reliability", 0.35)),
        "speed":       float(_get("supplier_weight_speed",       0.20)),
        "quality":     float(_get("supplier_weight_quality",     0.15)),
    })
    # Weights used under urgent/immediate conditions
    urgent_weights: Dict[str, float] = field(default_factory=lambda: {
        "cost":        float(_get("supplier_urgent_weight_cost",        0.15)),
        "reliability": float(_get("supplier_urgent_weight_reliability", 0.30)),
        "speed":       float(_get("supplier_urgent_weight_speed",       0.40)),
        "quality":     float(_get("supplier_urgent_weight_quality",     0.15)),
    })
    # On-time delivery rate below which Judge raises a warning
    low_reliability_threshold: float = field(
        default_factory=lambda: float(_get("supplier_low_reliability_threshold", 0.6))
    )


# ── AI conflict resolution ─────────────────────────────────────

@dataclass
class ConflictConfig:
    # Confidence above which AI resolutions are auto-applied (no user prompt)
    auto_apply_threshold: float = field(
        default_factory=lambda: float(_get("conflict_auto_apply_threshold", 0.85))
    )


# ── Singleton instances (import these in agents) ───────────────

inventory_config  = InventoryConfig()
supplier_config   = SupplierConfig()
conflict_config   = ConflictConfig()
