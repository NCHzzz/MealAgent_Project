from typing import AsyncGenerator, List, Dict, Any

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


def _build_filter_operand(path: List[str], operator: str, value_key: str, value) -> Dict:
    operand: Dict = {"path": path, "operator": operator}
    operand[value_key] = value
    return operand


def _combine_operands(operands: List[Dict]) -> Dict | None:
    if not operands:
        return None
    if len(operands) == 1:
        return operands[0]
    return {"operator": "And", "operands": operands}


from MealAgent.tools.utils.profile_targets import (
    ensure_profile_loaded,
    resolve_user_id,
)


@tool
async def constraints_guard_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    diet_types: List[str] | None = None,
    exclude_allergens: List[str] | None = None,
    max_cooking_time: int | None = None,
    required_device: str | None = None,
    exclude_devices: list[str] | None = None,
    user_id: str | None = None,
    base_lm=None,
    complex_lm=None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    Merge diet/allergen/time/equipment preferences into a single Weaviate `where` clause.

    Environment contract:
      Reads
        • `profile_crud_tool.profile` for default diet type, allergens, max cooking time, devices.
      Writes
        • `constraints_guard_tool.filters`
            - `objects[0].where`: Weaviate `where` payload (may be `{}` when no constraints).
            - `metadata`: derived parameters (`diet_types`, `exclude_allergens`, `max_cooking_time`, etc.).

    Behaviour:
      • If profile data is available, use it as defaults; explicit arguments override profile values.
      • If no constraints are resolved, the tool still writes an empty `where` object and `has_filters=False`.

    Decision hints:
      • Planning and search tools should **not fail** when `filters` is missing; treat it as “no constraints”.
      • Frontend should ignore `constraints_guard_tool.filters` objects (they are for internal use only, `display=False`).
    """
    yield Response("🔒 Applying dietary constraints and preferences...")

    resolved_user_id = resolve_user_id(tree_data, user_id)
    profile, profile_loaded = await ensure_profile_loaded(
        tree_data,
        client_manager,
        user_id=resolved_user_id,
        base_lm=base_lm,
        complex_lm=complex_lm,
        **kwargs,
    )
    if profile_loaded:
        yield Response("👤 Loaded your saved profile to personalize dietary filters.")
    profile = profile or {}

    # Input resolution (kwargs fallback)
    diet_types = diet_types or kwargs.get("diet_types") or (
        [profile.get("diet_type")] if isinstance(profile.get("diet_type"), str) else profile.get("diet_type", [])
    ) or []
    exclude_allergens = exclude_allergens or kwargs.get("exclude_allergens") or profile.get("allergens", []) or []

    if max_cooking_time is None:
        max_cooking_time = kwargs.get("max_cooking_time")
        if max_cooking_time is None and profile.get("max_cooking_time_min"):
            max_cooking_time = profile.get("max_cooking_time_min")

    required_device = (required_device or kwargs.get("required_device") or "").strip() or None
    if not required_device and profile.get("available_equipment"):
        available = profile.get("available_equipment", [])
        if isinstance(available, list) and available:
            required_device = available[0]

    exclude_devices = exclude_devices or kwargs.get("exclude_devices") or []

    # Build operands
    operands: list[Dict] = []

    if diet_types:
        operands.append(_build_filter_operand(["diet_type"], "ContainsAny", "valueTextArray", diet_types))
    if exclude_allergens:
        allergens_filter = _build_filter_operand(["allergens"], "ContainsAny", "valueTextArray", exclude_allergens)
        operands.append({"operator": "Not", "operands": [allergens_filter]})

    if isinstance(max_cooking_time, int):
        operands.append({"path": ["cooking_time"], "operator": "LessThanEqual", "valueInt": int(max_cooking_time)})
    if required_device:
        operands.append({"path": ["devices"], "operator": "ContainsAny", "valueTextArray": [required_device]})
    if exclude_devices:
        operands.append({
            "operator": "Not",
            "operands": [{"path": ["devices"], "operator": "ContainsAny", "valueTextArray": exclude_devices}],
        })

    where_clause = _combine_operands(operands)

    # Emit filters (per design: only filters output, no report)
    yield Result(
        name="filters",
        objects=[{"where": where_clause or {}}],
        metadata={
            "has_filters": bool(operands),
            "diet_types": diet_types,
            "exclude_allergens": exclude_allergens,
            "max_cooking_time": max_cooking_time if isinstance(max_cooking_time, int) else None,
            "required_device": required_device,
            "exclude_devices": exclude_devices,
        },
        payload_type="generic",
        display=False,
    )
    if operands:
        yield Response("✅ Constraints applied successfully")
    else:
        yield Response("ℹ️ No constraints specified")


