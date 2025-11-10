from typing import AsyncGenerator, Dict

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager
from elysia import tool


@tool
async def time_device_guard_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    max_cooking_time: int | None = None,
    required_device: str | None = None,
    exclude_devices: list[str] | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Generate optional time/equipment filters for Weaviate Recipe queries.

    Environment reads:
      - environment["profile_crud_tool"]["profile"] (optional - reads max_cooking_time_min, available_equipment)
    Writes: environment["time_device_guard_tool"]["filters"]
    """
    yield "Generating time/device filters..."

    # Try to read from profile first, then fallback to parameters
    profile_results = tree_data.environment.find("profile_crud_tool", "profile")
    if profile_results and profile_results[0].objects:
        profile = profile_results[0].objects[0]
        if not max_cooking_time and profile.get("max_cooking_time_min"):
            max_cooking_time = profile.get("max_cooking_time_min")
        if not required_device and profile.get("available_equipment"):
            # Use first available equipment as required (or could use all)
            available = profile.get("available_equipment", [])
            if available and isinstance(available, list) and len(available) > 0:
                required_device = available[0]  # Or could require all via ContainsAll

    max_cooking_time = max_cooking_time if isinstance(max_cooking_time, int) else kwargs.get("max_cooking_time")
    required_device = (required_device or kwargs.get("required_device") or "").strip() or None
    exclude_devices = exclude_devices or kwargs.get("exclude_devices") or []

    operands: list[Dict] = []

    if isinstance(max_cooking_time, int):
        operands.append({
            "path": ["cooking_time"],
            "operator": "LessThanEqual",
            "valueInt": int(max_cooking_time),
        })

    # Recipe schema should have `devices` (text[]) field.
    # Note: If Recipe schema doesn't have this field, filter will be skipped by Weaviate.
    if required_device:
        operands.append({
            "path": ["devices"],
            "operator": "ContainsAny",
            "valueTextArray": [required_device],
        })

    if exclude_devices:
        operands.append({
            "operator": "Not",
            "operands": [{
                "path": ["devices"],
                "operator": "ContainsAny",
                "valueTextArray": exclude_devices,
            }],
        })

    where_clause: Dict | None
    if not operands:
        where_clause = None
    elif len(operands) == 1:
        where_clause = operands[0]
    else:
        where_clause = {"operator": "And", "operands": operands}

    yield Result(name="filters", objects=[{"where": where_clause or {}}], metadata={"has_filters": bool(operands)})
    yield "Time/Device filters generated"


