from typing import AsyncGenerator, Dict

from elysia.tree.objects import TreeData, Result, Error
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

    Writes: environment["time_device_guard_tool"]["filters"]
    """
    yield "Generating time/device filters..."

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

    # Assume Recipe has `devices` (text[]). If not present, filters will be benign.
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


