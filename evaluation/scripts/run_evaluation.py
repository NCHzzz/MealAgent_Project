"""Run maintained MealAgent evaluation methods.

This module intentionally delegates to ``run_single_method`` instead of using
the removed legacy scenario-runner stack. It keeps the public CLI stable while
only exposing evaluation methods that exist in this repository.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from evaluation.scripts.run_single_method import (  # noqa: E402
    run_llm_judge_test,
    run_nutrition_error_test,
)


SUPPORTED_METHODS = ["nutrition_error", "llm_judge"]


async def run_evaluation(
    methods: Optional[list[str]] = None,
    use_mock: bool = False,
) -> None:
    """Run selected maintained evaluation methods."""
    methods_to_run = methods or SUPPORTED_METHODS

    print("=" * 80)
    print("MealAgent Evaluation Runner")
    print("=" * 80)
    print(f"Methods: {', '.join(methods_to_run)}")

    for method in methods_to_run:
        print(f"\n→ Running {method}...")
        if method == "nutrition_error":
            await run_nutrition_error_test(
                use_weaviate=not use_mock,
                load_all=not use_mock,
            )
        elif method == "llm_judge":
            await run_llm_judge_test(
                use_weaviate=not use_mock,
                load_all=not use_mock,
            )
        else:
            raise ValueError(f"Unsupported evaluation method: {method}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run maintained MealAgent evaluation methods",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m evaluation.scripts.run_evaluation --use-mock --methods nutrition_error
  python -m evaluation.scripts.run_evaluation --methods nutrition_error llm_judge
        """,
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=SUPPORTED_METHODS,
        help="Evaluation methods to run (default: all maintained methods)",
    )
    parser.add_argument(
        "--use-mock",
        action="store_true",
        help="Use deterministic mock data where supported",
    )

    args = parser.parse_args()
    asyncio.run(run_evaluation(methods=args.methods, use_mock=args.use_mock))


if __name__ == "__main__":
    main()
