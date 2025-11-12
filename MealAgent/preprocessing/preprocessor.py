"""
MealAgent Preprocessor (Task 1.4.3)

This script uses Elysia's official Preprocessor API to generate
metadata summaries for collections and store them in `ELYSIA_METADATA__`.

Reference: https://weaviate.github.io/elysia/Reference/Preprocessor/
"""

from typing import List
import os
from elysia.preprocessing.collection import preprocess
from elysia.util.client import ClientManager


TARGET_COLLECTIONS: List[str] = [
    "Recipe",
    "FdcFood",
    "FdcNutrient",
    "FdcPortion",
]


def _collections_from_env(defaults: List[str]) -> List[str]:
    env_val = os.getenv("MEAL_AGENT_PREPROCESS_COLLECTIONS", "").strip()
    if not env_val:
        return defaults
    return [c.strip() for c in env_val.split(",") if c.strip()]


def run() -> None:
    collections = _collections_from_env(TARGET_COLLECTIONS)
    # Use default ClientManager (reads env-configured settings)
    client_manager = ClientManager()
    # Keep sample sizes modest to control token usage during summary
    preprocess(
        collection_names=collections,
        client_manager=client_manager,
        min_sample_size=int(os.getenv("PREPROCESS_MIN_SAMPLE", "10")),
        max_sample_size=(
            int(os.getenv("PREPROCESS_MAX_SAMPLE"))
            if os.getenv("PREPROCESS_MAX_SAMPLE")
            else None
        ),
        num_sample_tokens=int(os.getenv("PREPROCESS_NUM_TOKENS", "30000")),
        force=os.getenv("PREPROCESS_FORCE", "false").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    run()


# (No standalone warm-ups; the official preprocessor samples objects and touches indexes.)


    


