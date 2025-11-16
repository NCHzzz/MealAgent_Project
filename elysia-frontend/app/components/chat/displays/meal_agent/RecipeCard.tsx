"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { RecipeCardPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import DisplayPagination from "../../components/DisplayPagination";

interface RecipeCardProps {
  recipes: RecipeCardPayload[];
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

const RecipeCard: React.FC<RecipeCardProps> = ({
  recipes,
  handleResultPayloadChange,
}) => {
  if (recipes.length === 0) return null;

  const formatMacro = (value: number, unit: string = "g") => {
    return `${value.toFixed(1)}${unit}`;
  };

  const formatKcal = (value: number) => {
    return `${value.toFixed(0)} kcal`;
  };

  return (
    <DisplayPagination layout="horizontal" itemsPerPage={3}>
      {recipes.map((recipe, idx) => {
        const [imageLoaded, setImageLoaded] = useState(false);
        const [imageError, setImageError] = useState(false);

        return (
          <motion.div
            key={`${recipe.food_id}-${idx}`}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: idx * 0.1 }}
            className="w-full h-full"
          >
            <Card
              className="h-full bg-background_alt border-secondary/10 hover:border-primary/20 transition-all cursor-pointer"
              onClick={() =>
                handleResultPayloadChange?.("recipe_card", recipe)
              }
            >
              {/* Image */}
              {recipe.image_link && (
                <div className="relative w-full aspect-square overflow-hidden bg-secondary/5 rounded-t-lg">
                  {!imageLoaded && !imageError && (
                    <Skeleton className="absolute inset-0 w-full h-full" />
                  )}
                  {!imageError && (
                    <motion.img
                      src={recipe.image_link}
                      alt={recipe.dish_name}
                      className={`w-full h-full object-cover transition-all duration-500 ${
                        imageLoaded ? "opacity-100" : "opacity-0"
                      }`}
                      onLoad={() => setImageLoaded(true)}
                      onError={() => setImageError(true)}
                    />
                  )}
                </div>
              )}

              <CardHeader>
                <CardTitle className="text-base line-clamp-2">
                  {recipe.dish_name}
                </CardTitle>
                <div className="flex flex-wrap gap-1 mt-2">
                  {recipe.diet_type?.map((diet) => (
                    <Badge key={diet} variant="outline" className="text-xs">
                      {diet}
                    </Badge>
                  ))}
                  {recipe.cooking_time && (
                    <Badge variant="outline" className="text-xs">
                      {recipe.cooking_time} min
                    </Badge>
                  )}
                </div>
              </CardHeader>

              <CardContent className="space-y-3">
                {/* Macros */}
                {recipe.macros_per_serving && (
                  <div>
                    <p className="text-xs text-secondary mb-1">Per Serving</p>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <p className="text-secondary">Calories</p>
                        <p className="font-semibold text-primary">
                          {formatKcal(recipe.macros_per_serving.kcal)}
                        </p>
                      </div>
                      <div>
                        <p className="text-secondary">Protein</p>
                        <p className="font-semibold text-primary">
                          {formatMacro(recipe.macros_per_serving.protein_g)}
                        </p>
                      </div>
                      <div>
                        <p className="text-secondary">Fat</p>
                        <p className="font-semibold text-primary">
                          {formatMacro(recipe.macros_per_serving.fat_g)}
                        </p>
                      </div>
                      <div>
                        <p className="text-secondary">Carbs</p>
                        <p className="font-semibold text-primary">
                          {formatMacro(recipe.macros_per_serving.carb_g)}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Allergens */}
                {recipe.allergens && recipe.allergens.length > 0 && (
                  <div>
                    <p className="text-xs text-secondary mb-1">Allergens</p>
                    <div className="flex flex-wrap gap-1">
                      {recipe.allergens.map((allergen) => (
                        <Badge
                          key={allergen}
                          variant="destructive"
                          className="text-xs"
                        >
                          {allergen}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Serving Size */}
                {recipe.serving_size && (
                  <p className="text-xs text-secondary">
                    Serves: {recipe.serving_size}
                  </p>
                )}
              </CardContent>
            </Card>
          </motion.div>
        );
      })}
    </DisplayPagination>
  );
};

export default RecipeCard;

