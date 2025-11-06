from typing import AsyncGenerator, List, Dict

from elysia.tree.objects import TreeData, Result, Error
from elysia.util.client import ClientManager
from elysia import tool


def _build_filter_operand(path: List[str], operator: str, value_key: str, value) -> Dict:
    operand: Dict = {"path": path, "operator": operator}
    operand[value_key] = value
    return operand


@tool
async def diet_allergen_guard_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    diet_types: List[str] | None = None,
    exclude_allergens: List[str] | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Generate Weaviate 'where' filters for diet types and allergens.

    Writes: environment["diet_allergen_guard_tool"]["filters"]
    """
    yield "Generating diet/allergen filters..."

    # Accept from kwargs or environment in future; for now prioritize parameters
    diet_types = diet_types or kwargs.get("diet_types") or []
    exclude_allergens = exclude_allergens or kwargs.get("exclude_allergens") or []

    operands: List[Dict] = []

    # Diet types: assume Recipe has `diet_type` (text or text[]). Use ContainsAny for arrays or Equal for single.
    if diet_types:
        # Use ContainsAny to match any requested diets
        operands.append(
            _build_filter_operand([
                "diet_type"
            ], "ContainsAny", "valueTextArray", diet_types)
        )

    # Allergens: assume Recipe has `allergens` (text[]). Exclude any that are in user's allergens.
    if exclude_allergens:
        # Use Not over ContainsAny to exclude recipes containing any of these allergens
        allergens_filter = _build_filter_operand(["allergens"], "ContainsAny", "valueTextArray", exclude_allergens)
        operands.append({"operator": "Not", "operands": [allergens_filter]})

    where_clause: Dict | None
    if not operands:
        where_clause = None
    elif len(operands) == 1:
        where_clause = operands[0]
    else:
        where_clause = {"operator": "And", "operands": operands}

    yield Result(name="filters", objects=[{"where": where_clause or {}}], metadata={"has_filters": bool(operands)})
    yield "Diet/Allergen filters generated"


