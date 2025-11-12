from typing import AsyncGenerator, Dict, Any, List

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


def _validate_macro_targets(
    total_macros: Dict[str, float],
    targets: Dict[str, float],
    tolerance_percent: float = 0.15,
) -> Dict[str, Any]:
    """Validate that plan macros are within tolerance of targets."""
    violations = []
    warnings = []

    for key in ["kcal", "protein_g", "fat_g", "carb_g"]:
        target_val = targets.get(key, 0.0)
        actual_val = total_macros.get(key, 0.0)

        if target_val <= 0:
            continue

        deviation = abs(actual_val - target_val) / target_val
        if deviation > tolerance_percent:
            violations.append({
                "macro": key,
                "target": target_val,
                "actual": actual_val,
                "deviation_percent": deviation * 100,
            })
        elif deviation > tolerance_percent * 0.7:  # Warning threshold
            warnings.append({
                "macro": key,
                "target": target_val,
                "actual": actual_val,
                "deviation_percent": deviation * 100,
            })

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
    }


def _validate_constraints(
    plan: Dict[str, Any],
    diet_types: List[str] | None = None,
    exclude_allergens: List[str] | None = None,
) -> Dict[str, Any]:
    """Validate that plan meals respect diet/allergen constraints."""
    violations = []

    for meal_key, meal_data in plan.get("meals", {}).items():
        recipe = meal_data.get("recipe", {})
        recipe_id = recipe.get("food_id", "")

        # Check diet type (if Recipe has diet_type field)
        if diet_types:
            recipe_diet = recipe.get("diet_type")
            if recipe_diet:
                recipe_diets = [recipe_diet] if isinstance(recipe_diet, str) else recipe_diet
                if not any(dt in recipe_diets for dt in diet_types):
                    violations.append({
                        "meal": meal_key,
                        "recipe_id": recipe_id,
                        "type": "diet_mismatch",
                        "expected": diet_types,
                        "actual": recipe_diets,
                    })

        # Check allergens (if Recipe has allergens field)
        if exclude_allergens:
            recipe_allergens = recipe.get("allergens", [])
            if recipe_allergens:
                overlap = set(recipe_allergens) & set(exclude_allergens)
                if overlap:
                    violations.append({
                        "meal": meal_key,
                        "recipe_id": recipe_id,
                        "type": "allergen_violation",
                        "forbidden_allergens": list(overlap),
                    })

    return {
        "valid": len(violations) == 0,
        "violations": violations,
    }


@tool
async def plan_validate_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    macro_tolerance_percent: float = 0.15,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Validate daily plan against constraints and macro targets.

    Environment reads:
      - environment["plan_assemble_day_tool"]["plan"]
      - environment["target_resolver_tool"]["resolved"] (or macro_calc_tool.targets)
      - environment["profile_crud_tool"]["profile"] (optional - for constraints)
    Environment writes:
      - environment["plan_validate_tool"]["report"]

    Decision hints:
      - If plan_validate_tool.report.valid is True, the plan meets all constraints and targets.
      - If plan_validate_tool.report.valid is False, consider adjusting the plan or constraints.
    """
    yield Response("Validating plan...")

    # Read plan
    plan_results = tree_data.environment.find("plan_assemble_day_tool", "plan")
    if not plan_results or not plan_results[0]["objects"]:
        yield Error("Plan not found. Run plan_assemble_day_tool first.")
        return

    plan = plan_results[0]["objects"][0]

    # Read targets
    targets_results = tree_data.environment.find("target_resolver_tool", "resolved")
    if not targets_results or not targets_results[0]["objects"]:
        # Fallback to macro_calc_tool targets
        targets_results = tree_data.environment.find("macro_calc_tool", "targets")
        if not targets_results or not targets_results[0]["objects"]:
            yield Error("Targets not found. Run target_resolver_tool or macro_calc_tool first.")
            return

    targets = targets_results[0]["objects"][0]

    # Read profile for constraints (optional)
    profile_results = tree_data.environment.find("profile_crud_tool", "profile")
    diet_types = None
    exclude_allergens = None
    if profile_results and profile_results[0]["objects"]:
        profile = profile_results[0]["objects"][0]
        diet_type = profile.get("diet_type")
        if diet_type:
            diet_types = [diet_type] if isinstance(diet_type, str) else diet_type
        exclude_allergens = profile.get("allergens", [])

    # Validate macros
    total_macros = plan.get("total_macros", {})
    macro_validation = _validate_macro_targets(total_macros, targets, macro_tolerance_percent)

    # Validate constraints
    constraint_validation = _validate_constraints(plan, diet_types, exclude_allergens)

    # Build report
    report = {
        "plan_id": plan.get("plan_id"),
        "plan_type": plan.get("plan_type", "day"),
        "valid": macro_validation["valid"] and constraint_validation["valid"],
        "macro_validation": macro_validation,
        "constraint_validation": constraint_validation,
        "total_macros": total_macros,
        "targets": targets,
        "summary": {
            "macro_violations": len(macro_validation["violations"]),
            "macro_warnings": len(macro_validation["warnings"]),
            "constraint_violations": len(constraint_validation["violations"]),
        },
    }

    # Stream response first for immediate feedback
    if report["valid"]:
        yield Response("Plan validation passed")
    else:
        yield Response(f"Plan validation failed: {report['summary']['macro_violations']} macro violations, {report['summary']['constraint_violations']} constraint violations")
    
    # Then yield Result for data consistency
    yield Result(
        name="report",
        objects=[report],
        metadata={"valid": report["valid"], "violations_count": report["summary"]["macro_violations"] + report["summary"]["constraint_violations"]},
        payload_type="generic",
    )

