---
title: Environment Keys Reference - MealAgent
---

This document lists common Environment keys used by MealAgent tools (tree_data.environment).

Convention: environment[tool_name][name]

| Tool | Reads | Writes |
|------|-------|--------|
| profile_crud_tool | - | profile |
| macro_calc_tool | profile | targets |
| diet_allergen_guard_tool | profile | filters |
| time_device_guard_tool | profile | filters |
| query_tool | filters | results |
| query_postprocessing_tool | results | deduped |
| score_and_rank_tool | deduped, targets | topk |
| calculate_recipe_macros_tool | Recipe by id | macros (and updates Recipe.macros_per_serving, ingredient_fdc_map) |
| plan_assemble_day_tool | topk, targets | plan |
| plan_validate_tool | plan | report |
| build_shopping_tool | plan | items |
| target_resolver_tool | profile, request params | resolved |
| plan_assemble_weekly_tool | daily plans/topk | plan |
| variety_guard_tool | plan | report |
| pantry_crud_tool | - | state |
| pantry_diff_tool | build_shopping_tool.items, pantry_crud_tool.state | diff |
| suggest_substitutes_tool | plan or recipe | substitutes |
| apply_substitute_tool | plan, substitutes | updated_plan |
| gap_calc_tool | plan/weekly_plan, targets | deficits |
| suggest_snack_tool | deficits | snack_suggestions |
| apply_snack_tool | plan, snack_suggestions | updated_plan |
| micronutrient_check_tool | plan/weekly_plan | totals |
| suggest_micros_foods_tool | micros_report | micros_foods |
| meal_parser_tool | raw_meal_text | parsed_meal |
| nutrition_calc_tool | parsed_meal, FdcFood/FdcPortion | calculated |
| profile_update_tool | calculated | updated_profile |
| meal_history_tool | user_id | history |
| cook_mode_tool | recipe_id | cook_steps |
| explain_tool | environment snapshot | explanation |

Notes:
- Tools should keep payloads small; store identifiers or summaries when possible.
- The VN→EN macros tool persists `macros_per_serving` and `ingredient_fdc_map` on `Recipe` for caching.
- Names are indicative; actual module paths are under `elysia/MealAgent/tools/**` when implemented.


