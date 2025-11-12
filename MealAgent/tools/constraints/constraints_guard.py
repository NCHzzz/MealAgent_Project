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


@tool
async def constraints_guard_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    diet_types: List[str] | None = None,
    exclude_allergens: List[str] | None = None,
    max_cooking_time: int | None = None,
    required_device: str | None = None,
    exclude_devices: list[str] | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Merge diet/allergen and time/device filters into a single where-clause.

    Environment interface:
    - Reads:
      - profile_crud_tool.profile (optional defaults for diet/allergens/equipment)
    - Writes:
      - constraints_guard_tool.filters: [{ where: <Filter JSON> }]
      - constraints_guard_tool.report: [{ ...inputs used..., has_constraints }]

    Decision hints:
    - If constraints_guard_tool.filters exists, search tools should use it.
    - The report indicates whether any constraint was actually applied.
    """
    yield Response("Generating combined constraints (diet/allergen + time/device)...")

    # Read profile for defaults
    profile_results = tree_data.environment.find("profile_crud_tool", "profile")
    profile = profile_results[0]["objects"][0] if (profile_results and profile_results[0]["objects"]) else {}

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

    # Emit filters
    yield Result(
        name="filters",
        objects=[{"where": where_clause or {}}],
        metadata={"has_filters": bool(operands)},
        payload_type="generic",
    )

    # Emit a compact report
    report: Dict[str, Any] = {
        "diet_types": diet_types,
        "exclude_allergens": exclude_allergens,
        "max_cooking_time": max_cooking_time if isinstance(max_cooking_time, int) else None,
        "required_device": required_device,
        "exclude_devices": exclude_devices,
        "has_constraints": bool(diet_types or exclude_allergens or max_cooking_time or required_device or exclude_devices),
    }
    yield Result(
        name="report",
        objects=[report],
        metadata={"has_constraints": report["has_constraints"]},
        payload_type="generic",
    )
    yield Response("Combined constraints generated")


