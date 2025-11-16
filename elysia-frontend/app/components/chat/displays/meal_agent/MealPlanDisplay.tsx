"use client";

import React from "react";
import { motion } from "framer-motion";
import { MealPlanPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import DisplayPagination from "../../components/DisplayPagination";

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

  const renderDailyPlan = (plan: MealPlanPayload) => {
    if (plan.plan_type !== "day" || !plan.meals) return null;

    const meals = Object.entries(plan.meals).map(([key, meal]) => ({
      key,
      ...meal,
    }));

    return (
      <Card className="w-full bg-background_alt border-secondary/10">
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle className="text-lg">Daily Meal Plan</CardTitle>
            <Badge
              variant={plan.validation?.valid ? "default" : "destructive"}
              className="ml-2"
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
                  <div>
                    <h4 className="font-semibold text-primary capitalize">
                      {meal.meal_type}
                    </h4>
                    <p className="text-sm text-secondary">
                      {meal.recipe.dish_name}
                    </p>
                  </div>
                  <Badge variant="outline" className="text-xs">
                    {meal.servings}x serving{meal.servings !== 1 ? "s" : ""}
                  </Badge>
                </div>
                {meal.recipe.macros_per_serving && (
                  <div className="flex gap-4 text-xs text-secondary mt-2">
                    <span>
                      {formatKcal(meal.macros.kcal)} | {formatMacro(meal.macros.protein_g)} P |{" "}
                      {formatMacro(meal.macros.fat_g)} F | {formatMacro(meal.macros.carb_g)} C
                    </span>
                  </div>
                )}
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

          {/* Validation Warnings */}
          {plan.validation && !plan.validation.valid && (
            <div className="pt-3 border-t border-secondary/10">
              <p className="text-xs text-destructive">
                ⚠ Plan has validation issues. Check macro or constraint violations.
              </p>
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
                <Badge variant="outline" className="text-xs">
                  Variety: {plan.variety_score.toFixed(1)}/100
                </Badge>
              )}
              <Badge
                variant={plan.validation?.valid ? "default" : "destructive"}
                className="text-xs"
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
                  {Object.entries(day.meals).map(([mealKey, meal]) => (
                    <div
                      key={mealKey}
                      className="flex justify-between items-center text-sm"
                    >
                      <span className="text-secondary capitalize">
                        {meal.meal_type}:
                      </span>
                      <span className="text-primary">{meal.recipe.dish_name}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Summary */}
          <div className="pt-3 border-t border-secondary/10">
            <h5 className="font-semibold text-sm mb-2">Weekly Summary</h5>
            <div className="grid grid-cols-2 gap-4 text-sm">
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

