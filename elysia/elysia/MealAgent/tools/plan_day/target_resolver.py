from typing import AsyncGenerator, Dict, Any

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool


@tool
async def target_resolver_tool(
    tree_data: TreeData,
    client_manager: ClientManager,  # signature consistency
    query_targets: Dict[str, float] | None = None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Resolve nutritional targets from query parameters vs profile defaults.

    Priority:
      1. Query parameters (if provided) - user override
      2. Profile targets (from macro_calc_tool)
      3. Default values (fallback)

    Environment reads:
      - environment["macro_calc_tool"]["targets"] (profile targets)
    Environment writes:
      - environment["target_resolver_tool"]["resolved"]
    """
    yield Response("Resolving nutritional targets...")

    # Read profile targets from environment
    targets_results = tree_data.environment.find("macro_calc_tool", "targets")
    profile_targets = None
    if targets_results and targets_results[0]["objects"]:
        profile_targets = targets_results[0]["objects"][0]

    # Priority: query_targets > profile_targets > defaults
    resolved = {}
    
    if query_targets:
        # Use query targets as override
        resolved = {
            "tdee_kcal": float(query_targets.get("tdee_kcal", 0)),
            "protein_g": float(query_targets.get("protein_g", 0)),
            "fat_g": float(query_targets.get("fat_g", 0)),
            "carb_g": float(query_targets.get("carb_g", 0)),
            "source": "query_override",
        }
    elif profile_targets:
        # Use profile targets
        resolved = {
            "tdee_kcal": float(profile_targets.get("tdee_kcal", 2000)),
            "protein_g": float(profile_targets.get("protein_g", 150)),
            "fat_g": float(profile_targets.get("fat_g", 67)),
            "carb_g": float(profile_targets.get("carb_g", 200)),
            "source": "profile",
        }
    else:
        # Default fallback
        resolved = {
            "tdee_kcal": 2000.0,
            "protein_g": 150.0,
            "fat_g": 67.0,
            "carb_g": 200.0,
            "source": "default",
        }

    yield Result(
        name="resolved",
        objects=[resolved],
        metadata={"source": resolved.get("source")},
        payload_type="generic",
    )
    yield Response(f"Targets resolved from {resolved.get('source')}: {resolved['tdee_kcal']:.0f} kcal")

