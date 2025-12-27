# LLM Judge Evaluation Summary Report

Generated: 2025-12-27 17:32:39

## Overview

- **Total Evaluations**: 53
- **Meal Plans (Suggested)**: 39
- **Meal Logs (Accepted/Actual)**: 14

## Performance Distribution

- **Excellent (≥80)**: 6 (11.3%)
- **Good (70-80)**: 37 (69.8%)
- **Fair (60-70)**: 10 (18.9%)
- **Poor (<60)**: 0 (0.0%)

## Aggregated Scores

### Overall Score
- Mean: 73.25
- Median: 74.25
- Std: 6.62
- Range: 53.2 - 86.2

### Nutrition Score
- Mean: 68.57
- Median: 70.00
- Std: 10.53

### Variety Score
- Mean: 75.76
- Median: 75.00
- Std: 7.47

### Balance Score
- Mean: 72.28
- Median: 75.00
- Std: 7.04

### Feasibility Score
- Mean: 76.40
- Median: 78.00
- Std: 6.29

## Common Issues

### Low Protein (<50g below target)
**Count**: 36 plans

### High Calories (>500kcal above target)
**Count**: 15 plans

### High Fat (>50g above target)
**Count**: 16 plans

### Low Variety (Score <40)
**Count**: 0 plans

### Poor Balance (Score <40)
**Count**: 0 plans

## Top 5 Best Plans

1. Plan ID: `meal_logs_898812d6-bd00-49e0-98f6-e2443890c8e6_2025-12-17` - Score: 86.2 (MealLogEntry)
2. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_e9ab26e1d94c_day_day_3` - Score: 83.5 (MealPlan)
3. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_8b7837bb5786_day_day_1` - Score: 82.5 (MealPlan)
4. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_8b7837bb5786_day_day_5` - Score: 81.5 (MealPlan)
5. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_8b7837bb5786_day_day_0` - Score: 81.0 (MealPlan)

## Top 5 Worst Plans

1. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_c8f83c502949` - Score: 66.5 (MealPlan)
2. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_14e061bd5fc5` - Score: 66.8 (MealPlan)
3. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_a23bbc66af59` - Score: 67.0 (MealPlan)
4. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_e7578410a1c8` - Score: 67.5 (MealPlan)
5. Plan ID: `meal_logs_898812d6-bd00-49e0-98f6-e2443890c8e6_2025-12-16` - Score: 67.5 (MealLogEntry)

## Recommendations

### For Meal Plan Generation:
1. **Increase Protein**: Many plans lack sufficient protein. Consider adding more lean protein sources.
2. **Control Calories**: Many plans exceed calorie targets. Reduce portion sizes or choose lower-calorie options.
3. **Reduce Fat**: High-fat plans are common. Use cooking methods that reduce fat (steaming, grilling).
4. **Improve Variety**: Add more diverse dishes to avoid repetition.
5. **Better Balance**: Distribute macros more evenly across meals.

### For System Improvement:
- Review and fix data quality issues (especially MealLogEntry with unrealistic macros)
- Implement better macro validation before saving plans
- Add variety constraints to meal plan generation
- Improve portion size estimation
