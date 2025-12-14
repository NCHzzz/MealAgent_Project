"use client";

import React, { useCallback, useState } from "react";
import { motion } from "framer-motion";
import { MealPlanPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import DisplayPagination from "../../components/DisplayPagination";
import { ImageIcon } from "lucide-react";
import { acceptPlan } from "@/app/api/acceptPlan";

type DailyMeal = NonNullable<MealPlanPayload["meals"]>[string];
type WeeklyMeal = NonNullable<
  NonNullable<MealPlanPayload["days"]>[string]["meals"]
>[string];
type AnyMeal = DailyMeal | WeeklyMeal;

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

  const [acceptingPlanId, setAcceptingPlanId] = useState<string | null>(null);
  const [acceptMessage, setAcceptMessage] = useState<string | null>(null);
  const [acceptError, setAcceptError] = useState<string | null>(null);

  const formatMacro = (value: number, unit: string = "g") => {
    // Round to 1 decimal place for consistency
    return `${Math.round(value * 10) / 10}${unit}`;
  };

  const formatKcal = (value: number) => {
    // Round to nearest integer for kcal display
    return `${Math.round(value)} kcal`;
  };

  type Macros = { kcal?: number; protein_g?: number; fat_g?: number; carb_g?: number };

  const computeMealMacros = (meal: AnyMeal): {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
    isTotal: boolean;
    main?: Macros;
    total?: Macros;
  } => {
    // Prefer explicitly provided totals, then per-meal, then recipe serving macros
    const total: Macros | undefined = (meal as any)?.macros_total || (meal as any)?.macros;
    const main: Macros | undefined =
      (meal as any)?.macros_main || meal?.recipe?.macros_per_serving || (meal as any)?.macros;
    const pick: Macros = total || main || {};
    return {
      kcal: pick?.kcal ?? 0,
      protein_g: pick?.protein_g ?? 0,
      fat_g: pick?.fat_g ?? 0,
      carb_g: pick?.carb_g ?? 0,
      isTotal: Boolean(total),
      main,
      total,
    };
  };

  const getRecipeImage = (meal?: AnyMeal) => {
    // Special case: Use default white rice image for default white rice recipe
    const dishName = meal?.recipe?.dish_name?.toLowerCase() || "";
    const foodId = meal?.recipe?.food_id || "";
    
    if (foodId === "default_white_rice" || 
        (dishName.includes("cơm trắng") || dishName.includes("com trang") || dishName.includes("white rice")) && 
         foodId === "default_white_rice") {
      return "/image/com_trang.jpg";
    }
    
    // Accept multiple possible image keys to be resilient to upstream changes
    return (
      meal?.recipe?.image_link ||
      // some tool outputs may use alternative keys
      (meal?.recipe as any)?.image_url ||
      (meal?.recipe as any)?.image ||
      // occasionally image is attached directly on meal
      (meal as any)?.image_link ||
      undefined
    );
  };

  const handleAcceptPlan = useCallback(
    async (plan: MealPlanPayload) => {
      setAcceptMessage(null);
      setAcceptError(null);

      if (!plan.plan_id || !plan.user_id) {
        setAcceptError(
          "Thiếu user hoặc plan_id. Đã gửi tín hiệu tới agent để xử lý."
        );
        handleResultPayloadChange?.("accept_plan", {
          plan_id: plan.plan_id,
          user_id: plan.user_id,
        });
        return;
      }

      setAcceptingPlanId(plan.plan_id);
      const res = await acceptPlan(plan.user_id, plan.plan_id);
      setAcceptingPlanId(null);

      if (res.success) {
        setAcceptMessage(res.message || "Đã chấp nhận kế hoạch");
        // Only show popup notification, do not trigger refresh or navigation
        // User can manually refresh meal history if needed
      } else {
        setAcceptError(res.error || "Không thể chấp nhận kế hoạch");
      }
    },
    [handleResultPayloadChange]
  );

  const openRecipeDetail = (
    e: React.MouseEvent,
    recipe: AnyMeal["recipe"] | { dish_name?: string; image_link?: string }
  ) => {
    e.stopPropagation();
    handleResultPayloadChange?.("recipe_detail", recipe);
  };

  const renderMealImage = (imageSrc: string | undefined, alt?: string) => (
    <div className="w-16 h-16 rounded-lg overflow-hidden bg-secondary/5 border border-secondary/10 shadow-sm ml-3 shrink-0">
      {imageSrc ? (
        <img
          src={imageSrc}
          alt={alt || "Recipe image"}
          className="w-full h-full object-cover"
          loading="lazy"
          onError={(e) => {
            const target = e.currentTarget;
            target.style.display = "none";
          }}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-secondary/10 to-secondary/5">
          <ImageIcon className="w-6 h-6 text-secondary/50" />
        </div>
      )}
    </div>
  );

  const renderAccompaniments = (
    items?: {
      type?: string;
      recipe?: { dish_name?: string; image_link?: string };
      servings?: number;
      macros?: { kcal?: number; protein_g?: number; fat_g?: number; carb_g?: number };
    }[]
  ) => {
    if (!items || items.length === 0) return null;

    const computeMacros = (item: typeof items[number]) => {
      const servings = item.servings ?? 1;
      const baseMacros =
        item.macros ||
        (item.recipe as any)?.macros_per_serving ||
        (item as any)?.macros_per_serving ||
        {};
      const kcal = (baseMacros.kcal || 0) * servings;
      const protein_g = (baseMacros.protein_g || 0) * servings;
      const fat_g = (baseMacros.fat_g || 0) * servings;
      const carb_g = (baseMacros.carb_g || 0) * servings;
      return { kcal, protein_g, fat_g, carb_g };
    };

    return (
      <div className="mt-3 border-t border-secondary/10 pt-3 space-y-1">
        <p className="text-xs font-semibold uppercase text-secondary tracking-wide">
          Sides & extras
        </p>
        {items.map((item, idx) => (
          <div
            key={`${item.recipe?.dish_name}-${idx}`}
            className="flex justify-between items-start text-xs bg-background/70 rounded p-2 border border-secondary/10 hover:border-primary/20 transition-colors cursor-pointer"
            onClick={(e) => {
              if (item.recipe) {
                openRecipeDetail(e, item.recipe);
              }
            }}
          >
            <div className="flex items-center gap-2">
              {renderMealImage(
                getRecipeImage(item as AnyMeal),
                item.recipe?.dish_name
              )}
              <div className="flex flex-col">
                <span className="text-primary font-medium capitalize">
                  {item.type || "extra"}
                </span>
                <span className="text-secondary">
                  {item.recipe?.dish_name || "Unknown dish"}
                </span>
                <div className="flex items-center gap-2 text-secondary text-[11px]">
                  {item.servings && (
                    <span>
                      {item.servings} serving{item.servings !== 1 ? "s" : ""}
                    </span>
                  )}
                  {item.servings && <span className="text-secondary/50">•</span>}
                  <span>{formatKcal(computeMacros(item).kcal)}</span>
                </div>
              </div>
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
          <div className="flex justify-between items-center gap-2">
            <CardTitle className="text-lg">Daily Meal Plan</CardTitle>
            <Button
              size="sm"
              variant="default"
              onClick={() => handleAcceptPlan(plan)}
              disabled={acceptingPlanId === plan.plan_id}
            >
              {acceptingPlanId === plan.plan_id ? "Đang lưu..." : "Accept plan"}
            </Button>
          </div>
          {(acceptMessage || acceptError) && (
            <div className="text-sm mt-2">
              {acceptMessage && <span className="text-green-600">{acceptMessage}</span>}
              {acceptError && <span className="text-red-500">{acceptError}</span>}
            </div>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Meals */}
          <div className="space-y-3">
            {meals.map((meal, idx) => (
              <motion.div
                key={meal.key}
                onClick={(e) => openRecipeDetail(e, meal.recipe)}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.15 }}
                className="p-4 bg-background rounded-lg border border-secondary/10 shadow-sm hover:shadow-md transition-shadow cursor-pointer"
              >
                <div className="flex justify-between items-start mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="font-bold text-primary capitalize text-base">
                        {meal.meal_type === "breakfast" ? "🌅" : meal.meal_type === "lunch" ? "🍽️" : "🌙"} {meal.meal_type}
                      </h4>
                      <Badge variant="outline" className="text-xs">
                        {meal.servings}x serving{meal.servings !== 1 ? "s" : ""}
                      </Badge>
                    </div>
                    <p className="text-sm font-medium text-primary mt-1">
                      {meal.recipe?.dish_name || "Unknown dish"}
                    </p>
                    {meal.recipe?.cooking_time && (
                      <p className="text-xs text-secondary mt-1 flex items-center gap-1">
                        <span>⏱️</span>
                        <span>{meal.recipe.cooking_time} min</span>
                      </p>
                    )}
                  </div>
                  {renderMealImage(getRecipeImage(meal), meal.recipe?.dish_name)}
                </div>
                {/* Macros per meal */}
                <div className="mt-3 pt-2 border-t border-secondary/5">
                  {(() => {
                    const macros = computeMealMacros(meal);
                    const showTotal =
                      macros.total &&
                      macros.main &&
                      Math.abs((macros.total?.kcal || 0) - (macros.main?.kcal || 0)) > 1;
                    return (
                      <div className="space-y-1">
                        <div className="flex items-center gap-3 text-xs">
                          <span className="text-secondary/80 font-medium">Nutrition:</span>
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="px-2 py-0.5 bg-primary/10 text-primary rounded font-medium">
                              {formatKcal(macros.main?.kcal ?? macros.kcal)}
                            </span>
                            <span className="text-secondary">
                              {formatMacro(macros.main?.protein_g ?? macros.protein_g)} P
                            </span>
                            <span className="text-secondary">
                              {formatMacro(macros.main?.fat_g ?? macros.fat_g)} F
                            </span>
                            <span className="text-secondary">
                              {formatMacro(macros.main?.carb_g ?? macros.carb_g)} C
                            </span>
                          </div>
                        </div>
                        {showTotal && (
                          <div className="text-[11px] text-secondary/70 pl-16">
                            Total with sides:{" "}
                            <span className="font-medium text-primary">
                              {formatKcal(macros.total?.kcal || macros.kcal)}
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
                {renderAccompaniments(meal.accompaniments)}
              </motion.div>
            ))}
          </div>

          {/* Total Macros */}
          <div className="pt-4 border-t border-secondary/10 bg-background/50 rounded-lg p-4">
            <h5 className="font-semibold text-sm mb-3 flex items-center gap-2">
              <span className="text-lg">📊</span>
              Total Daily Macros
            </h5>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="flex flex-col items-center p-3 bg-primary/5 rounded-lg border border-primary/10">
                <p className="text-secondary text-xs mb-1 font-medium">Calories</p>
                <p className="font-bold text-lg text-primary">
                  {formatKcal(plan.total_macros.kcal)}
                </p>
              </div>
              <div className="flex flex-col items-center p-3 bg-blue-500/5 rounded-lg border border-blue-500/10">
                <p className="text-secondary text-xs mb-1 font-medium">Protein</p>
                <p className="font-bold text-lg text-blue-600 dark:text-blue-400">
                  {formatMacro(plan.total_macros.protein_g)}
                </p>
              </div>
              <div className="flex flex-col items-center p-3 bg-yellow-500/5 rounded-lg border border-yellow-500/10">
                <p className="text-secondary text-xs mb-1 font-medium">Fat</p>
                <p className="font-bold text-lg text-yellow-600 dark:text-yellow-400">
                  {formatMacro(plan.total_macros.fat_g)}
                </p>
              </div>
              <div className="flex flex-col items-center p-3 bg-green-500/5 rounded-lg border border-green-500/10">
                <p className="text-secondary text-xs mb-1 font-medium">Carbs</p>
                <p className="font-bold text-lg text-green-600 dark:text-green-400">
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
          <div className="flex justify-between items-center gap-2">
            <CardTitle className="text-lg">Weekly Meal Plan</CardTitle>
            <Button
              size="sm"
              variant="default"
              onClick={() => handleAcceptPlan(plan)}
              disabled={acceptingPlanId === plan.plan_id}
            >
              {acceptingPlanId === plan.plan_id ? "Đang lưu..." : "Accept plan"}
            </Button>
          </div>
          {(acceptMessage || acceptError) && (
            <div className="text-sm mt-2">
              {acceptMessage && <span className="text-green-600">{acceptMessage}</span>}
              {acceptError && <span className="text-red-500">{acceptError}</span>}
            </div>
          )}
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
                        onClick={(e) => {
                          if (meal.recipe) {
                            openRecipeDetail(e, meal.recipe);
                          }
                        }}
                        className={`flex flex-col gap-2 text-sm p-2 bg-background/50 rounded border border-secondary/10 transition-colors ${
                          meal.recipe ? "hover:border-primary/30 cursor-pointer" : "cursor-default"
                        }`}
                      >
                        <div className="flex justify-between items-start gap-3">
                          <div className="flex-1">
                            <div className="flex items-center gap-2">
                              <span className="text-secondary capitalize font-medium">
                                {meal.meal_type}:
                              </span>
                              <span className="text-primary font-semibold">
                                {meal.recipe?.dish_name || "Unknown dish"}
                              </span>
                            </div>
                            {meal.recipe?.cooking_time && (
                              <p className="text-xs text-secondary mt-1 flex items-center gap-1">
                                <span>⏱️</span>
                                <span>{meal.recipe.cooking_time} min</span>
                              </p>
                            )}
                            {/* Nutrition info */}
                            {(() => {
                              const macros = computeMealMacros(meal);
                              return (
                                <div className="flex items-center gap-2 text-xs mt-1 flex-wrap">
                                  <span className="px-2 py-0.5 bg-primary/10 text-primary rounded font-medium">
                                    {formatKcal(macros.kcal)}
                                  </span>
                                  <span className="text-secondary">
                                    {formatMacro(macros.protein_g)} P
                                  </span>
                                  <span className="text-secondary">
                                    {formatMacro(macros.fat_g)} F
                                  </span>
                                  <span className="text-secondary">
                                    {formatMacro(macros.carb_g)} C
                                  </span>
                                </div>
                              );
                            })()}
                          </div>
                          {renderMealImage(getRecipeImage(meal), meal.recipe?.dish_name)}
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
          transition={{ duration: 0.15 }}
        >
          <div className="mx-auto w-full max-w-6xl">
            {plan.plan_type === "day"
              ? renderDailyPlan(plan)
              : renderWeeklyPlan(plan)}
          </div>
        </motion.div>
      ))}
    </DisplayPagination>
  );
};

export default MealPlanDisplay;

