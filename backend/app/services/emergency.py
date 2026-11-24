"""Per-client emergency rules (spec §6).

Life-safety wording is NOT configurable: the fixed safety block in the master template is
always spoken first, even when a tool fails. What each client configures is:
  - whether a category should trigger the emergency transfer,
  - approved additional instructions for that category (read verbatim by the assistant),
  - extra custom categories (label + approved instructions).
The assistant never invents instructions: it only reads the fixed block and these texts."""

import re

from pydantic import BaseModel, Field, field_validator

# Keys are stored in calls.emergency_type and in each client's emergency_rules: never rename or
# reorder existing keys. New categories are appended; clients without a stored rule for them
# get the defaults (transfer allowed, no extra instructions).
BUILTIN = {
    "gas": "Gas smell",
    "co": "Carbon monoxide alarm",
    "smoke": "Smoke or fire",
    "burning_smell": "Burning electrical smell",
    "sparks": "Electrical sparks",
    "dangerous_malfunction": "Dangerous HVAC malfunction",
    "refrigerant_leak": "Refrigerant leak",
    "refrigeration_failure": "Walk-in cooler or freezer failure",
}
MAX_CUSTOM = 10


class EmergencyRule(BaseModel):
    key: str = Field(min_length=2, max_length=40)
    label: str = Field(min_length=2, max_length=60)
    transfer: bool = True
    instructions: str = Field(default="", max_length=600)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", v):
            raise ValueError("key must be lowercase letters, digits or underscores")
        return v


def default_rules() -> list[dict]:
    return [
        {"key": k, "label": v, "transfer": True, "instructions": ""} for k, v in BUILTIN.items()
    ]


def effective_rules(stored: list | None) -> list[dict]:
    """Built-ins are always present (in a fixed order); custom rules follow."""
    by_key = {r.get("key"): r for r in (stored or []) if isinstance(r, dict)}
    out = []
    for key, label in BUILTIN.items():
        r = by_key.get(key, {})
        out.append(
            {
                "key": key,
                "label": label,
                "builtin": True,
                "transfer": bool(r.get("transfer", True)),
                "instructions": str(r.get("instructions") or ""),
            }
        )
    for r in stored or []:
        if isinstance(r, dict) and r.get("key") not in BUILTIN:
            out.append({**r, "builtin": False})
    return out


def validate_rules(rules: list[EmergencyRule]) -> list[dict]:
    keys = [r.key for r in rules]
    if len(set(keys)) != len(keys):
        raise ValueError("Each emergency category may appear once")
    custom = [r for r in rules if r.key not in BUILTIN]
    if len(custom) > MAX_CUSTOM:
        raise ValueError(f"At most {MAX_CUSTOM} custom emergency categories")
    for r in custom:
        if not r.instructions.strip():
            raise ValueError(f"Custom category '{r.label}' needs approved instructions")
    return [
        {
            "key": r.key,
            "label": BUILTIN.get(r.key, r.label),
            "transfer": r.transfer,
            "instructions": r.instructions.strip(),
        }
        for r in rules
    ]


def find_rule(stored: list | None, key: str | None, custom_category: str | None = None) -> dict:
    rules = effective_rules(stored)
    if key == "custom" and custom_category:
        wanted = custom_category.strip().lower()
        for r in rules:
            if not r["builtin"] and r["label"].lower() == wanted:
                return r
    for r in rules:
        if r["key"] == key and key != "custom":
            return r
    return {
        "key": "other",
        "label": "Other emergency",
        "builtin": True,
        "transfer": True,
        "instructions": "",
    }


def custom_labels(stored: list | None) -> list[str]:
    return [r["label"] for r in effective_rules(stored) if not r["builtin"]]
