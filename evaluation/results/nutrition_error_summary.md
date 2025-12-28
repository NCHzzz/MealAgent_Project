# Nutrition Error Evaluation Summary Report

Generated: 2025-12-28 16:20:34

## Overview

- **Total Evaluations**: 58
- **Meal Plans (Suggested)**: 41
- **Meal Logs (Accepted/Actual)**: 17

## Performance Distribution

- **Excellent (<10%)**: 35 (60.3%)
- **Good (10-15%)**: 23 (39.7%)
- **Fair (15-20%)**: 0 (0.0%)
- **Poor (≥20%)**: 0 (0.0%)

## Aggregated Metrics

### Overall Percentage Error
- Mean: 6.94%
- Median: 7.83%
- Std: 4.58%
- Range: 0.10% - 12.19%

### Protein Error
- Mean: 20.81%
- Median: 22.37%
- Std: 5.83%

### Carb Error
- Mean: 20.16%
- Median: 22.42%
- Std: 7.19%

### Fat Error
- Mean: 21.61%
- Median: 22.81%
- Std: 8.24%

### Calories Error
- Mean: 15.63%
- Median: 16.28%
- Std: 9.90%

## Aggregated MAE (Mean Absolute Error)

### Overall MAE
- Mean: 159.10
- Std: 268.51
- Range: 22.18 - 1356.38

### Protein MAE
- Mean: 105.59g
- Std: 172.50g

### Carb MAE
- Mean: 181.63g
- Std: 372.92g

### Fat MAE
- Mean: 92.33g
- Std: 150.21g

### Calories MAE
- Mean: 1542.52kcal
- Std: 3277.19kcal

## Common Issues

### Low Protein (<50g below target)
**Count**: 37 plans

### High Protein (>50g above target)
**Count**: 6 plans

### Low Calories (<500kcal below target)
**Count**: 7 plans

### High Calories (>500kcal above target)
**Count**: 20 plans

### High Carb (>100g above target)
**Count**: 21 plans

### High Fat (>50g above target)
**Count**: 21 plans

## Top 5 Best Plans (Lowest Error)

1. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_9766989a7edd` - Error: 0.10% (MealPlan)
2. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_8b7837bb5786_day_day_5` - Error: 0.60% (MealPlan)
3. Plan ID: `meal_logs_898812d6-bd00-49e0-98f6-e2443890c8e6_2026-01-01` - Error: 0.60% (MealLogEntry)
4. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_8b7837bb5786_day_day_2` - Error: 0.69% (MealPlan)
5. Plan ID: `meal_logs_898812d6-bd00-49e0-98f6-e2443890c8e6_2025-12-29` - Error: 0.69% (MealLogEntry)

## Top 5 Worst Plans (Highest Error)

1. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_4e3ea626c750` - Error: 12.19% (MealPlan)
2. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_e7578410a1c8` - Error: 12.19% (MealPlan)
3. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_545b8de2e09c` - Error: 12.19% (MealPlan)
4. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_14e061bd5fc5` - Error: 12.18% (MealPlan)
5. Plan ID: `898812d6-bd00-49e0-98f6-e2443890c8e6_plan_636f52b4d2df` - Error: 12.17% (MealPlan)

## Recommendations

### For Meal Plan Generation:
1. **Increase Protein**: Many plans lack sufficient protein. Consider adding more lean protein sources.
2. **Control Calories**: Many plans exceed calorie targets. Reduce portion sizes or choose lower-calorie options.
3. **Reduce Fat**: High-fat plans are common. Use cooking methods that reduce fat (steaming, grilling).
4. **Control Carbs**: Some plans exceed carb targets. Consider reducing portion sizes of carb-rich foods.
5. **Improve Overall Accuracy**: Focus on better macro distribution and portion size estimation.

### For System Improvement:
- Review and fix data quality issues (especially MealLogEntry with unrealistic macros)
- Implement better macro validation before saving plans
- Improve portion size estimation algorithms
- Consider user feedback and adjust targets accordingly
- Monitor and reduce outliers in nutrition calculations
