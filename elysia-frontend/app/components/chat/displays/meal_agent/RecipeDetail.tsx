"use client";

import React from "react";
import { motion } from "framer-motion";
import { RecipeCardPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ImageIcon, Clock, Users, ChefHat } from "lucide-react";

interface RecipeDetailProps {
  recipe: RecipeCardPayload;
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

const RecipeDetail: React.FC<RecipeDetailProps> = ({
  recipe,
  handleResultPayloadChange,
}) => {
  if (!recipe) {
    return null;
  }

  const formatMacro = (value: number, unit: string = "g") => {
    return `${value.toFixed(1)}${unit}`;
  };

  const formatKcal = (value: number) => {
    return `${value.toFixed(0)} kcal`;
  };

  const dishTypes = Array.isArray(recipe.dish_type)
    ? recipe.dish_type
    : recipe.dish_type
      ? [recipe.dish_type]
      : [];
  const dietTypes = Array.isArray(recipe.diet_type)
    ? recipe.diet_type
    : recipe.diet_type
      ? [recipe.diet_type]
      : [];
  const allergens = Array.isArray(recipe.allergens) ? recipe.allergens : [];
  const ingredientList = Array.isArray(recipe.ingredients_with_qty)
    ? recipe.ingredients_with_qty
    : Array.isArray(recipe.ingredients)
      ? recipe.ingredients
      : recipe.ingredients
        ? [recipe.ingredients]
        : [];
  const macros = recipe.macros_per_serving;
  const hasMacros = Boolean(macros && typeof macros.kcal === "number");

  // Extract cooking instructions from multiple possible shapes/fields.
  // Mirrors cook_mode_tool behaviour as much as possible on the frontend
  // so Calendar view always has reasonable guidance.
  const buildInstructionList = (): string[] => {
    const r: any = recipe;

    // 0) Preferred: structured array `cooking_method_array` (used by cook_mode_tool)
    if (Array.isArray(r.cooking_method_array) && r.cooking_method_array.length > 0) {
      return r.cooking_method_array
        .map((s: unknown) => (typeof s === "string" ? s.trim() : String(s ?? "")))
        .filter((s) => s.length > 0);
    }

    // 1) Structured steps from CookingSteps-like payload
    if (Array.isArray(r.steps) && r.steps.length > 0) {
      // steps: [{ index, instruction, ... }]
      if (typeof r.steps[0] === "object" && r.steps[0] !== null) {
        return r.steps
          .map((s: any) => s?.instruction)
          .filter((s: unknown): s is string => typeof s === "string" && s.trim().length > 0);
      }
      // steps: string[]
      if (typeof r.steps[0] === "string") {
        return r.steps.filter(
          (s: unknown): s is string => typeof s === "string" && s.trim().length > 0,
        );
      }
    }

    // 2) Single string with newlines or numbered bullets
    const stringCandidates: string[] = [
      r.cooking_instructions,
      r.instructions,
      r.method,
      r.directions,
      r.preparation,
    ].filter((s: unknown): s is string => typeof s === "string" && s.trim().length > 0);

    if (stringCandidates.length > 0) {
      const joined = stringCandidates.join("\n");
      // Split on newlines first, then fallback to ". " if needed
      const lines = joined
        .split(/\r?\n+/)
        .map((l) => l.trim())
        .filter((l) => l.length > 0);

      if (lines.length > 0) {
        return lines;
      }

      return joined
        .split(/(?<=[.!?])\s+/)
        .map((l) => l.trim())
        .filter((l) => l.length > 0);
    }

    // 3) Array of strings in alternative fields
    const arrayCandidates: unknown[] = [
      r.cooking_steps,
      r.cooking_steps_text,
      r.instructions_list,
    ];

    for (const candidate of arrayCandidates) {
      if (Array.isArray(candidate)) {
        const arr = (candidate as unknown[]).filter(
          (s: unknown): s is string => typeof s === "string" && s.trim().length > 0,
        );
        if (arr.length > 0) return arr;
      }
    }

    // 4) Fallback: synthesise generic steps from ingredients (like cook_mode_tool)
    const ingredientsSource =
      r.ingredients_with_qty ||
      r.ingredients ||
      ingredientList ||
      ([] as unknown[]);

    const ingredientsArr = Array.isArray(ingredientsSource)
      ? ingredientsSource
      : [];

    if (ingredientsArr.length > 0) {
      const synthetic: string[] = [];
      synthetic.push("Chuẩn bị đầy đủ tất cả nguyên liệu ở trên.");
      ingredientsArr.forEach((ing: unknown) => {
        const text =
          typeof ing === "string"
            ? ing
            : typeof ing === "object" && ing !== null
            ? JSON.stringify(ing)
            : String(ing);
        synthetic.push(`Sơ chế / chuẩn bị: ${text}`);
      });
      synthetic.push(
        "Tiến hành nấu món ăn theo phương pháp phù hợp (xào, luộc, chiên, hầm...) cho tới khi chín và nêm nếm vừa ăn.",
      );
      return synthetic;
    }

    return [];
  };

  const instructionList = buildInstructionList();

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="w-full"
    >
      <Card className="bg-background_alt border-secondary/10">
        {/* Image Section */}
        <div className="relative w-full aspect-video overflow-hidden bg-gradient-to-br from-secondary/10 to-secondary/5 rounded-t-lg">
          {recipe.image_link ? (
            <img
              src={recipe.image_link}
              alt={recipe.dish_name || "Recipe image"}
              className="w-full h-full object-cover"
              loading="lazy"
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <ImageIcon className="w-16 h-16 text-secondary/40" />
            </div>
          )}
        </div>

        <CardHeader>
          <CardTitle className="text-2xl mb-4">{recipe.dish_name}</CardTitle>
          
          {/* Basic Info */}
          <div className="flex flex-wrap gap-2 mb-4">
            {dishTypes.map((dish) => (
              <Badge key={dish} className="text-sm border border-secondary/20">
                <ChefHat className="w-3 h-3 mr-1" />
                {dish}
              </Badge>
            ))}
            {recipe.cooking_time && (
              <Badge className="text-sm border border-secondary/20">
                <Clock className="w-3 h-3 mr-1" />
                {recipe.cooking_time} min
              </Badge>
            )}
            {recipe.serving_size && (
              <Badge className="text-sm border border-secondary/20">
                <Users className="w-3 h-3 mr-1" />
                Serves {recipe.serving_size}
              </Badge>
            )}
          </div>

          {/* Diet Types */}
          {dietTypes.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-4">
              {dietTypes.map((diet) => (
                <Badge key={diet} className="text-sm border border-secondary/20">
                  {diet}
                </Badge>
              ))}
            </div>
          )}

          {/* Allergens */}
          {allergens.length > 0 && (
            <div className="mb-4">
              <p className="text-sm font-semibold text-secondary mb-2">⚠️ Allergens</p>
              <div className="flex flex-wrap gap-2">
                {allergens.map((allergen) => (
                  <Badge
                    key={allergen}
                    className="text-sm bg-destructive/10 text-destructive border border-destructive/20"
                  >
                    {allergen}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardHeader>

        <CardContent className="space-y-6">
          {/* Nutrition Information */}
          {hasMacros && macros && (
            <div>
              <h3 className="text-lg font-semibold mb-3">📊 Nutrition (Per Serving)</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-primary/5 rounded-lg p-4 text-center">
                  <p className="text-xs text-secondary mb-1">Calories</p>
                  <p className="text-xl font-bold text-primary">
                    {formatKcal(macros.kcal)}
                  </p>
                </div>
                <div className="bg-primary/5 rounded-lg p-4 text-center">
                  <p className="text-xs text-secondary mb-1">Protein</p>
                  <p className="text-xl font-bold text-primary">
                    {formatMacro(macros.protein_g)}
                  </p>
                </div>
                <div className="bg-primary/5 rounded-lg p-4 text-center">
                  <p className="text-xs text-secondary mb-1">Fat</p>
                  <p className="text-xl font-bold text-primary">
                    {formatMacro(macros.fat_g)}
                  </p>
                </div>
                <div className="bg-primary/5 rounded-lg p-4 text-center">
                  <p className="text-xs text-secondary mb-1">Carbs</p>
                  <p className="text-xl font-bold text-primary">
                    {formatMacro(macros.carb_g)}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Ingredients */}
          {ingredientList.length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3">🥘 Ingredients</h3>
              <div className="bg-secondary/5 rounded-lg p-4">
                <ul className="space-y-2">
                  {ingredientList.map((ingredient, idx) => (
                    <li key={`${ingredient}-${idx}`} className="flex items-start">
                      <span className="text-primary mr-2">•</span>
                      <span className="text-sm">{ingredient}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* Cooking Instructions */}
          {instructionList.length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3">👩‍🍳 Hướng dẫn nấu</h3>
              <div className="bg-background rounded-lg border border-secondary/10 p-4 space-y-2">
                {instructionList.map((step, idx) => (
                  <div
                    key={`${idx}-${step.slice(0, 20)}`}
                    className="flex items-start gap-3"
                  >
                    <div className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                      {idx + 1}
                    </div>
                    <p className="text-sm leading-relaxed text-primary">{step}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Missing Nutrition Warning */}
          {!hasMacros && (
            <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4">
              <p className="text-sm text-yellow-600 dark:text-yellow-400">
                ⚠️ Nutrition information is not available for this recipe. 
                The system will calculate it automatically when needed.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default RecipeDetail;

