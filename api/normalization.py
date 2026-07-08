import os
import json
import pandas as pd
from io import StringIO
from typing import Optional, List
from api.llm_client import acomplete, acomplete_json
from api.config import conflict_config

# Client no longer needed here as llm_client handles it.

# ─────────────────────────────────────────────
# SCHEMA DEFINITIONS
# ─────────────────────────────────────────────

SCHEMAS = {
    "inventory": {
        "required": ["product_id", "product_name", "quantity_in_stock", "reorder_threshold"],
        "optional": ["warehouse", "supplier_info", "unit_cost", "avg_daily_consumption", "lead_time_days"]
    },
    "supplier": {
        "required": ["supplier_name", "base_cost_per_unit", "on_time_delivery_rate", "lead_time_days", "quality_rating"],
        "optional": ["historical_issues", "contact_info"]
    },
    "shipment": {
        "required": ["shipment_id", "expected_delivery"],
        "optional": ["product_id", "quantity", "supplier", "carrier", "actual_delivery", "is_on_time", "carrier_avg_delay"]
    }
}


# ─────────────────────────────────────────────
# STEP 1: Detect file type
# ─────────────────────────────────────────────

async def detect_file_type(headers: list[str], sample_rows: list[dict]) -> str:
    prompt = f"""
You are a supply chain data expert. Given these CSV headers and sample rows, 
identify what type of supply chain data this file contains.

Headers: {headers}
Sample rows (first 3): {json.dumps(sample_rows[:3], default=str)}

Choose EXACTLY one of these types:
- inventory: contains product stock levels, quantities, reorder points
- supplier: contains supplier/vendor information, costs, delivery rates
- shipment: contains order/shipment tracking, delivery dates, carriers

Respond with ONLY the type word, nothing else. Example: inventory
"""
    try:
        raw = await acomplete(prompt)
        file_type = raw.strip().lower()
    except Exception:
        file_type = "inventory"

    if file_type not in ["inventory", "supplier", "shipment"]:
        header_str = " ".join(headers).lower()
        if any(w in header_str for w in ["stock", "quantity", "reorder", "product"]):
            return "inventory"
        elif any(w in header_str for w in ["supplier", "vendor", "cost_per", "delivery_rate"]):
            return "supplier"
        elif any(w in header_str for w in ["shipment", "carrier", "tracking", "delivery_date"]):
            return "shipment"
        return "inventory"

    return file_type


# ─────────────────────────────────────────────
# STEP 2: Map columns
# ─────────────────────────────────────────────

async def map_columns_with_ai(
    headers: list[str],
    sample_rows: list[dict],
    file_type: str
) -> dict:
    schema = SCHEMAS[file_type]
    all_fields = schema["required"] + schema["optional"]

    prompt = f"""
You are a supply chain data normalization expert.

I have a CSV file of type "{file_type}" with these headers:
{headers}

Sample data (first 3 rows):
{json.dumps(sample_rows[:3], default=str)}

Map each raw CSV header to the most appropriate field from this target schema:
Required fields: {schema["required"]}
Optional fields: {schema["optional"]}

Rules:
1. Only map headers that clearly correspond to a schema field
2. Each schema field can only be mapped ONCE (use the best match)
3. If a header doesn't match any schema field, omit it
4. For boolean fields like is_on_time, values like "yes/no", "1/0", "true/false" all count
5. Return ONLY valid JSON, no explanation, no markdown, no backticks

Expected output format:
{{"raw_header_name": "schema_field_name", "another_header": "another_field"}}

Example:
{{"units_available": "quantity_in_stock", "sku_code": "product_id", "item_name": "product_name"}}
"""
    try:
        mapping = await acomplete_json(prompt, fallback={})
        valid_mapping = {
            k: v for k, v in mapping.items()
            if v in all_fields and k in headers
        }
        return valid_mapping
    except Exception:
        return {}


# ─────────────────────────────────────────────
# STEP 3: Apply mapping + normalize
# ─────────────────────────────────────────────

def apply_mapping_and_normalize(
    df: pd.DataFrame,
    mapping: dict,
    file_type: str
) -> tuple[list[dict], list[str]]:
    schema = SCHEMAS[file_type]
    df_renamed = df.rename(columns=mapping)

    missing_required = [
        field for field in schema["required"]
        if field not in df_renamed.columns
    ]

    all_fields = schema["required"] + schema["optional"]
    available_fields = [f for f in all_fields if f in df_renamed.columns]

    normalized_rows = []
    for _, row in df_renamed.iterrows():
        record = {}
        for field in available_fields:
            val = row[field]

            if field == "is_on_time":
                if str(val).lower() in ["1", "true", "yes"]:
                    val = True
                elif str(val).lower() in ["0", "false", "no"]:
                    val = False
                else:
                    val = None

            elif field in ["quantity_in_stock", "reorder_threshold", "lead_time_days",
                           "historical_issues", "quantity"]:
                try:
                    val = int(float(str(val).replace(",", "")))
                except (ValueError, TypeError):
                    val = None

            elif field in ["unit_cost", "avg_daily_consumption", "base_cost_per_unit",
                           "on_time_delivery_rate", "quality_rating", "carrier_avg_delay"]:
                try:
                    val = float(str(val).replace(",", "").replace("$", ""))
                    import math
                    if math.isnan(val):
                        val = None
                except (ValueError, TypeError):
                    val = None

            elif isinstance(val, float) and pd.isna(val):
                val = None
            else:
                val = str(val).strip() if val is not None else None

            record[field] = val

        normalized_rows.append(record)

    missing_required_set = set()
    for field in schema["required"]:
        if field not in df_renamed.columns:
            missing_required_set.add(field)
        else:
            if not all(row.get(field) is not None and str(row.get(field)).strip() != "" for row in normalized_rows):
                missing_required_set.add(field)
                
    missing_required = list(missing_required_set)

    return normalized_rows, missing_required


# ─────────────────────────────────────────────
# STEP 4: Detect conflicts
# ─────────────────────────────────────────────

def detect_conflicts(
    incoming_rows: list[dict],
    existing_rows: list[dict],
    file_type: str,
    existing_file_id: str,
    incoming_file_id: str
) -> list[dict]:
    name_key = {
        "inventory": "product_name",
        "supplier":  "supplier_name",
        "shipment":  "shipment_id"
    }[file_type]

    compare_fields = {
        "inventory": ["quantity_in_stock", "reorder_threshold", "unit_cost",
                      "avg_daily_consumption", "lead_time_days", "warehouse"],
        "supplier":  ["base_cost_per_unit", "on_time_delivery_rate", "lead_time_days",
                      "quality_rating", "historical_issues"],
        "shipment":  ["carrier", "expected_delivery", "quantity", "supplier", "carrier_avg_delay"]
    }[file_type]

    existing_index = {
        row.get(name_key, "").lower(): row
        for row in existing_rows
        if row.get(name_key)
    }

    conflicts = []
    for incoming in incoming_rows:
        name = str(incoming.get(name_key, "")).lower()
        if name in existing_index:
            existing = existing_index[name]
            for field in compare_fields:
                incoming_val = incoming.get(field)
                existing_val = existing.get(field)
                if (incoming_val is not None and existing_val is not None
                        and str(incoming_val) != str(existing_val)):
                    conflicts.append({
                        "table_name":   file_type,
                        "product_name": incoming.get(name_key),
                        "file_id_a":    existing_file_id,
                        "file_id_b":    incoming_file_id,
                        "field_name":   field,
                        "value_a":      str(existing_val),
                        "value_b":      str(incoming_val),
                        "resolution":   None
                    })

    return conflicts


# ─────────────────────────────────────────────
# STEP 4b: AI conflict resolution (T4.1)
# ─────────────────────────────────────────────

async def resolve_conflicts_with_ai(conflicts: List[dict]) -> List[dict]:
    """
    For each conflict, ask the LLM to suggest the best resolution with confidence.

    Returns the same list with two extra keys added to every conflict dict:
      - ai_resolution:  "use_existing" | "use_incoming" | "keep_both"
      - ai_confidence:  float  0.0–1.0
      - ai_reasoning:   str
      - auto_applied:   bool  (True when confidence >= conflict_config.auto_apply_threshold)
    """
    if not conflicts:
        return []

    # Build a compact representation for the LLM
    conflicts_text = json.dumps(
        [
            {
                "id": i,
                "field": c["field_name"],
                "entity": c["product_name"],
                "existing": c["value_a"],
                "incoming": c["value_b"],
            }
            for i, c in enumerate(conflicts)
        ],
        indent=2,
    )

    prompt = f"""You are a supply chain data steward.

The following field-level conflicts were detected when a new CSV upload differed from existing database records.
For each conflict decide which value to keep.

CONFLICTS:
{conflicts_text}

Resolution options:
- "use_existing" : keep the current database value (incoming is wrong / outdated)
- "use_incoming" : overwrite with the new value (incoming is correct / more recent)
- "keep_both"    : create a new record alongside the existing one

Rules:
1. Numeric quantities (stock levels, costs) — prefer the LARGER value if both are plausible, unless the new one is clearly a data error.
2. Dates — prefer the more RECENT date.
3. Text fields (warehouse, carrier) — prefer the incoming unless it looks like a truncation or typo.
4. Give HIGH confidence (>0.85) only when the choice is obvious.
5. Give LOW confidence (<0.60) when both values are plausible.

Respond ONLY in valid JSON — one entry per conflict id:
{{
  "resolutions": [
    {{"id": 0, "resolution": "use_incoming", "confidence": 0.91, "reasoning": "Newer stock count from updated shipment"}},
    {{"id": 1, "resolution": "use_existing",  "confidence": 0.75, "reasoning": "Existing cost is lower and more likely correct"}}
  ]
}}
"""

    parsed = await acomplete_json(
        prompt,
        fallback={"resolutions": []},
    )

    resolution_map = {
        r["id"]: r for r in parsed.get("resolutions", [])
    }

    threshold = conflict_config.auto_apply_threshold
    result = []
    for i, c in enumerate(conflicts):
        ai = resolution_map.get(i, {})
        resolution  = ai.get("resolution",  "use_incoming")
        confidence  = float(ai.get("confidence", 0.5))
        reasoning   = ai.get("reasoning",   "AI resolution unavailable")
        auto_applied = confidence >= threshold

        result.append({
            **c,
            "ai_resolution": resolution,
            "ai_confidence":  round(confidence, 3),
            "ai_reasoning":   reasoning,
            "auto_applied":   auto_applied,
        })

    return result


async def run_normalization_pipeline(
    csv_content: str,
    file_id: str,
    existing_db_rows: list[dict],
    existing_file_id: Optional[str] = None
) -> dict:
    df = pd.read_csv(StringIO(csv_content))
    df.columns = [c.strip() for c in df.columns]
    headers = list(df.columns)
    sample_rows = df.head(3).to_dict(orient="records")

    file_type = await detect_file_type(headers, sample_rows)
    mapping = await map_columns_with_ai(headers, sample_rows, file_type)
    normalized_rows, missing_required = apply_mapping_and_normalize(df, mapping, file_type)

    conflicts = []
    if existing_db_rows and existing_file_id:
        conflicts = detect_conflicts(
            incoming_rows=normalized_rows,
            existing_rows=existing_db_rows,
            file_type=file_type,
            existing_file_id=existing_file_id,
            incoming_file_id=file_id
        )

    # AI resolves each conflict automatically (T4.1)
    if conflicts:
        conflicts = await resolve_conflicts_with_ai(conflicts)

    return {
        "file_id":          file_id,
        "file_type":        file_type,
        "total_rows":       len(normalized_rows),
        "column_mapping":   mapping,
        "missing_required": missing_required,
        "preview_rows":     normalized_rows[:5],
        "all_rows":         normalized_rows,
        "conflicts":        conflicts,
        "can_commit":       len(missing_required) == 0
    }