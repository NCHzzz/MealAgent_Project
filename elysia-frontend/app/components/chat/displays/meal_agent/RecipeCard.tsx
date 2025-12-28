"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { RecipeCardPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import DisplayPagination from "../../components/DisplayPagination";
import { ImageIcon } from "lucide-react";
import RecipeDetail from "./RecipeDetail";

interface RecipeCardProps {
  recipes: RecipeCardPayload[];
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

// Component riêng cho mỗi recipe card để quản lý state
const RecipeCardItem: React.FC<{
  recipe: RecipeCardPayload;
  idx: number;
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}> = ({ recipe, idx, handleResultPayloadChange }) => {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);

  const formatMacro = (value: number, unit: string = "g") => {
    return `${value.toFixed(1)}${unit}`;
  };

  const formatKcal = (value: number) => {
    return `${value.toFixed(0)} kcal`;
  };

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
        onClick={() => handleResultPayloadChange?.("recipe_detail", recipe)}
      >
        {/* Image Section */}
        <div className="relative w-full aspect-square overflow-hidden bg-gradient-to-br from-secondary/10 to-secondary/5 rounded-t-lg">
          {recipe.image_link ? (
            <>
              {!imageLoaded && !imageError && (
                <Skeleton className="absolute inset-0 w-full h-full" />
              )}
              {imageError && (
                <div className="absolute inset-0 flex items-center justify-center bg-secondary/10">
                  <ImageIcon className="w-12 h-12 text-secondary/40" />
                </div>
              )}
              {!imageError && (
                <motion.img
                  src={recipe.image_link}
                  alt={recipe.dish_name || "Recipe image"}
                  className={`w-full h-full object-cover transition-all duration-500 ${
                    imageLoaded ? "opacity-100" : "opacity-0"
                  }`}
                  onLoad={() => setImageLoaded(true)}
                  onError={() => {
                    setImageError(true);
                    setImageLoaded(false);
                  }}
                  loading="lazy"
                />
              )}
            </>
          ) : (
            <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-secondary/10 to-secondary/5">
              <ImageIcon className="w-12 h-12 text-secondary/40" />
            </div>
          )}
        </div>

        <CardHeader>
          <CardTitle className="text-base line-clamp-2">
            {recipe.dish_name}
          </CardTitle>
          <div className="flex flex-wrap gap-1 mt-2">
            {recipe.diet_type?.map((diet) => (
              <Badge key={diet} className="text-xs border border-secondary/20">
                {diet}
              </Badge>
            ))}
            {recipe.cooking_time && (
              <Badge className="text-xs border border-secondary/20">
                {recipe.cooking_time} min
              </Badge>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-3">
          {/* Macros */}
          {recipe.macros_per_serving && (
            <div>
              <p className="text-xs text-secondary mb-1">Mỗi phần ăn</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <p className="text-secondary">Năng lượng</p>
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
                  <p className="text-secondary">Chất béo</p>
                  <p className="font-semibold text-primary">
                    {formatMacro(recipe.macros_per_serving.fat_g)}
                  </p>
                </div>
                <div>
                  <p className="text-secondary">Tinh bột</p>
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
              <p className="text-xs text-secondary mb-1">Dị ứng</p>
              <div className="flex flex-wrap gap-1">
                {recipe.allergens.map((allergen) => (
                  <Badge
                    key={allergen}
                    className="text-xs bg-destructive/10 text-destructive border border-destructive/20"
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
              Khẩu phần: {recipe.serving_size}
            </p>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

const RecipeCard: React.FC<RecipeCardProps> = ({
  recipes,
  handleResultPayloadChange,
}) => {
  const [selectedRecipe, setSelectedRecipe] = useState<RecipeCardPayload | null>(
    null
  );

  if (recipes.length === 0) return null;

  return (
    <div className="w-full flex flex-col gap-4">
      <DisplayPagination layout="horizontal" itemsPerPage={3}>
        {recipes.map((recipe, idx) => (
          <RecipeCardItem
            key={`${recipe.food_id}-${idx}`}
            recipe={recipe}
            idx={idx}
            handleResultPayloadChange={(type, payload) => {
              // Hiển thị chi tiết ngay trong view hiện tại
              setSelectedRecipe(payload as RecipeCardPayload);
              // Đồng thời kích hoạt cơ chế view chung (mở tab Result) nếu được cung cấp
              handleResultPayloadChange?.(type, payload);
            }}
          />
        ))}
      </DisplayPagination>

      {selectedRecipe && (
        <RecipeDetail
          recipe={selectedRecipe}
          handleResultPayloadChange={handleResultPayloadChange}
        />
      )}
    </div>
  );
};

export default RecipeCard;

