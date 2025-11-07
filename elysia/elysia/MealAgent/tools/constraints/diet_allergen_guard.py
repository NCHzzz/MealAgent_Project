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

    Environment reads:
      - environment["profile_crud_tool"]["profile"] (optional - reads diet_type, allergens)
    Writes: environment["diet_allergen_guard_tool"]["filters"]
    """
    yield "Generating diet/allergen filters..."

    # Try to read from profile first, then fallback to parameters
    profile_results = tree_data.environment.find("profile_crud_tool", "profile")
    if profile_results and profile_results[0].objects:
        profile = profile_results[0].objects[0]
        if not diet_types and profile.get("diet_type"):
            diet_types = [profile.get("diet_type")] if isinstance(profile.get("diet_type"), str) else profile.get("diet_type", [])
        if not exclude_allergens and profile.get("allergens"):
            exclude_allergens = profile.get("allergens", [])

    # Accept from kwargs or parameters as fallback
    diet_types = diet_types or kwargs.get("diet_types") or []
    exclude_allergens = exclude_allergens or kwargs.get("exclude_allergens") or []

    operands: List[Dict] = []

    # Diet types: Recipe schema should have `diet_type` (text or text[]).
    # Note: If Recipe schema doesn't have this field, filter will be skipped by Weaviate.
    if diet_types:
        # Use ContainsAny to match any requested diets
        operands.append(
            _build_filter_operand([
                "diet_type"
            ], "ContainsAny", "valueTextArray", diet_types)
        )

    # Allergens: Recipe schema should have `allergens` (text[]).
    # Note: If Recipe schema doesn't have this field, filter will be skipped by Weaviate.
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


