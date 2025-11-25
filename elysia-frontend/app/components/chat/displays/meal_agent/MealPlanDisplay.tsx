"use client";

import React from "react";
import { motion } from "framer-motion";
import { MealPlanPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import DisplayPagination from "../../components/DisplayPagination";

type DailyMeal = NonNullable<MealPlanPayload["meals"]>[string];
type WeeklyMeal = NonNullable<
  NonNullable<MealPlanPayload["days"]>[string]["meals"]
>[string];

interface MealPlanDisplayProps {
  plans: MealPlanPayload[];
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

const MealPlanDisplay: React.FC<MealPlanDisplayProps> = ({
  plans,
  handleResultPayloadChange,
}) => {
  if (plans.length === 0) return null;

  const formatMacro = (value: number, unit: string = "g") => {
    return `${value.toFixed(1)}${unit}`;
  };

  const formatKcal = (value: number) => {
    return `${value.toFixed(0)} kcal`;
  };

  const renderAccompaniments = (
    items?: {
      type?: string;
      recipe?: { dish_name?: string };
      servings?: number;
      macros?: { kcal?: number };
    }[]
  ) => {
    if (!items || items.length === 0) return null;
    return (
      <div className="mt-3 border-t border-secondary/10 pt-3 space-y-1">
        <p className="text-xs font-semibold uppercase text-secondary tracking-wide">
          Sides & extras
        </p>
        {items.map((item, idx) => (
          <div
            key={`${item.recipe?.dish_name}-${idx}`}
            className="flex justify-between items-start text-xs bg-background/70 rounded p-2"
          >
            <div className="flex flex-col">
              <span className="text-primary font-medium capitalize">
                {item.type || "extra"}
              </span>
              <span className="text-secondary">
                {item.recipe?.dish_name || "Unknown dish"}
              </span>
            </div>
            <div className="text-right text-secondary">
              {item.servings && (
                <p>
                  {item.servings} serving{item.servings !== 1 ? "s" : ""}
                </p>
              )}
              <p>{formatKcal(item.macros?.kcal || 0)}</p>
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderDailyPlan = (plan: MealPlanPayload) => {
    if (plan.plan_type !== "day" || !plan.meals) return null;

    const meals = (Object.entries(plan.meals) as [string, DailyMeal][]).map(
      ([key, meal]) => ({
        key,
        ...meal,
      })
    );

    return (
      <Card className="w-full bg-background_alt border-secondary/10">
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle className="text-lg">Daily Meal Plan</CardTitle>
            <Badge
              className={`ml-2 ${plan.validation?.valid ? "" : "bg-destructive/10 text-destructive"}`}
            >
              {plan.validation?.valid ? "Valid" : "Issues"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Meals */}
          <div className="space-y-3">
            {meals.map((meal, idx) => (
              <div
                key={meal.key}
                className="p-3 bg-background rounded-lg border border-secondary/5"
              >
                <div className="flex justify-between items-start mb-2">
                  <div className="flex-1">
                    <h4 className="font-semibold text-primary capitalize">
                      {meal.meal_type}
                    </h4>
                    <p className="text-sm text-secondary">
                      {meal.recipe?.dish_name || "Unknown dish"}
                    </p>
                    {meal.recipe?.cooking_time && (
                      <p className="text-xs text-secondary mt-1">
                        ⏱️ {meal.recipe.cooking_time} min
                      </p>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-1">
                  <Badge className="text-xs border border-secondary/20">
                    {meal.servings}x serving{meal.servings !== 1 ? "s" : ""}
                  </Badge>
                    {meal.recipe?.image_link && (
                      <div className="w-12 h-12 rounded overflow-hidden bg-secondary/5">
                        <img 
                          src={meal.recipe.image_link} 
                          alt={meal.recipe.dish_name}
                          className="w-full h-full object-cover"
                          onError={(e) => {
                            (e.target as HTMLImageElement).style.display = 'none';
                          }}
                        />
                      </div>
                    )}
                  </div>
                </div>
                {/* Macros per meal */}
                <div className="flex gap-4 text-xs text-secondary mt-2">
                  <span>
                    {formatKcal(meal.macros?.kcal || 0)} | {formatMacro(meal.macros?.protein_g || 0)} P |{" "}
                    {formatMacro(meal.macros?.fat_g || 0)} F | {formatMacro(meal.macros?.carb_g || 0)} C
                  </span>
                </div>
                {renderAccompaniments(meal.accompaniments)}
              </div>
            ))}
          </div>

          {/* Total Macros */}
          <div className="pt-3 border-t border-secondary/10">
            <h5 className="font-semibold text-sm mb-2">Total Daily Macros</h5>
            <div className="grid grid-cols-4 gap-2 text-sm">
              <div>
                <p className="text-secondary text-xs">Calories</p>
                <p className="font-semibold text-primary">
                  {formatKcal(plan.total_macros.kcal)}
                </p>
              </div>
              <div>
                <p className="text-secondary text-xs">Protein</p>
                <p className="font-semibold text-primary">
                  {formatMacro(plan.total_macros.protein_g)}
                </p>
              </div>
              <div>
                <p className="text-secondary text-xs">Fat</p>
                <p className="font-semibold text-primary">
                  {formatMacro(plan.total_macros.fat_g)}
                </p>
              </div>
              <div>
                <p className="text-secondary text-xs">Carbs</p>
                <p className="font-semibold text-primary">
                  {formatMacro(plan.total_macros.carb_g)}
                </p>
              </div>
            </div>
          </div>

          {/* Validation Details */}
          {plan.validation && (
            <div className="pt-3 border-t border-secondary/10 space-y-2">
              {!plan.validation.valid && (
                <div className="space-y-1">
                  {plan.validation.macro_validation && !plan.validation.macro_validation.valid && (
                    <div className="text-xs text-destructive">
                      ⚠ Macro violations: {plan.validation.macro_validation.violations?.length || 0} issue(s)
                    </div>
                  )}
                  {plan.validation.constraint_validation && !plan.validation.constraint_validation.valid && (
                    <div className="text-xs text-destructive">
                      ⚠ Constraint violations: {plan.validation.constraint_validation.violations?.length || 0} issue(s)
                    </div>
                  )}
                </div>
              )}
              {plan.validation.macro_validation?.warnings && plan.validation.macro_validation.warnings.length > 0 && (
                <div className="text-xs text-yellow-600 dark:text-yellow-400">
                  ℹ️ {plan.validation.macro_validation.warnings.length} minor deviation(s) detected
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    );
  };

  const renderWeeklyPlan = (plan: MealPlanPayload) => {
    if (plan.plan_type !== "week" || !plan.days) return null;

    const days = Object.entries(plan.days).map(([key, day]) => ({
      key,
      ...day,
    }));

    return (
      <Card className="w-full bg-background_alt border-secondary/10">
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle className="text-lg">Weekly Meal Plan</CardTitle>
            <div className="flex gap-2">
              {plan.variety_score !== undefined && (
                <Badge className="text-xs border border-secondary/20">
                  Variety: {plan.variety_score.toFixed(1)}/100
                </Badge>
              )}
              <Badge
                className={`text-xs ${plan.validation?.valid ? "" : "bg-destructive/10 text-destructive"}`}
              >
                {plan.validation?.valid ? "Valid" : "Issues"}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Days */}
          <div className="space-y-4">
            {days.map((day, idx) => (
              <div
                key={day.key}
                className="p-3 bg-background rounded-lg border border-secondary/5"
              >
                <div className="flex justify-between items-center mb-2">
                  <h4 className="font-semibold text-primary">
                    Day {idx + 1} {day.date && `(${day.date})`}
                  </h4>
                  <div className="text-xs text-secondary">
                    {formatKcal(day.total_macros.kcal)}
                  </div>
                </div>
                <div className="space-y-2">
                  {Object.entries(day.meals).map(
                    ([mealKey, meal]: [string, WeeklyMeal]) => (
                      <div
                        key={mealKey}
                        className="flex flex-col gap-2 text-sm p-2 bg-background/50 rounded"
                      >
                        <div className="flex justify-between items-start">
                          <div className="flex-1">
                            <span className="text-secondary capitalize font-medium">
                              {meal.meal_type}:
                            </span>
                            <span className="text-primary ml-2">
                              {meal.recipe.dish_name}
                            </span>
                          </div>
                          <div className="text-xs text-secondary ml-2">
                            {formatKcal(meal.macros?.kcal || 0)}
                          </div>
                        </div>
                        {renderAccompaniments(meal.accompaniments)}
                      </div>
                    )
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Summary */}
          <div className="pt-3 border-t border-secondary/10">
            <h5 className="font-semibold text-sm mb-2">Weekly Summary</h5>
            <div className="grid grid-cols-2 gap-4 text-sm mb-3">
              <div>
                <p className="text-secondary text-xs">Total Calories</p>
                <p className="font-semibold text-primary">
                  {formatKcal(plan.total_macros.kcal)}
                </p>
              </div>
              {plan.average_daily_macros && (
                <div>
                  <p className="text-secondary text-xs">Avg Daily Calories</p>
                  <p className="font-semibold text-primary">
                    {formatKcal(plan.average_daily_macros.kcal)}
                  </p>
                </div>
              )}
            </div>
            {/* Average Daily Macros */}
            {plan.average_daily_macros && (
              <div className="grid grid-cols-4 gap-2 text-xs">
                <div>
                  <p className="text-secondary">Protein</p>
                  <p className="font-semibold text-primary">
                    {formatMacro(plan.average_daily_macros.protein_g)}
                  </p>
                </div>
                <div>
                  <p className="text-secondary">Fat</p>
                  <p className="font-semibold text-primary">
                    {formatMacro(plan.average_daily_macros.fat_g)}
                  </p>
                </div>
                <div>
                  <p className="text-secondary">Carbs</p>
                  <p className="font-semibold text-primary">
                    {formatMacro(plan.average_daily_macros.carb_g)}
                  </p>
                </div>
              </div>
            )}
            {/* Validation Details */}
            {plan.validation && (
              <div className="mt-3 pt-3 border-t border-secondary/10 space-y-1">
                {!plan.validation.valid && (
                  <>
                    {plan.validation.macro_validation && !plan.validation.macro_validation.valid && (
                      <div className="text-xs text-destructive">
                        ⚠ Macro violations: {plan.validation.macro_validation.violations?.length || 0} issue(s)
                      </div>
                    )}
                    {plan.validation.constraint_validation && !plan.validation.constraint_validation.valid && (
                      <div className="text-xs text-destructive">
                        ⚠ Constraint violations: {plan.validation.constraint_validation.violations?.length || 0} issue(s)
                      </div>
                    )}
                    {plan.validation.variety_validation && !plan.validation.variety_validation.valid && (
                      <div className="text-xs text-destructive">
                        ⚠ Variety score {plan.variety_score?.toFixed(1) || 0}/100 below minimum
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <DisplayPagination>
      {plans.map((plan, idx) => (
        <motion.div
          key={idx}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: idx * 0.1 }}
        >
          {plan.plan_type === "day"
            ? renderDailyPlan(plan)
            : renderWeeklyPlan(plan)}
        </motion.div>
      ))}
    </DisplayPagination>
  );
};

export default MealPlanDisplay;

