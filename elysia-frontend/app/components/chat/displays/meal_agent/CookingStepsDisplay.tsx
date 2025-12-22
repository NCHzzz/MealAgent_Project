"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { CookingStepsPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ImageIcon } from "lucide-react";
import DisplayPagination from "../../components/DisplayPagination";

interface CookingStepsDisplayProps {
  steps: CookingStepsPayload[];
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

const CookingStepsDisplay: React.FC<CookingStepsDisplayProps> = ({
  steps,
  handleResultPayloadChange,
}) => {
  if (steps.length === 0) return null;

  return (
    <DisplayPagination>
      {steps.map((stepData, idx) => (
        <CookingStepsCard
          key={`${stepData.food_id ?? "meal"}-${idx}`}
          stepData={stepData}
          index={idx}
        />
      ))}
    </DisplayPagination>
  );
};

interface CookingStepsCardProps {
  stepData: CookingStepsPayload;
  index: number;
}

const formatTime = (seconds: number) => {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
};

const CookingStepsCard: React.FC<CookingStepsCardProps> = ({
  stepData,
  index,
}) => {
  const stepList = Array.isArray(stepData.steps) ? stepData.steps : [];
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);

  // Prefer explicit cooking_time from Recipe collection (minutes) if available.
  const totalTimeMinutesFromRecipe =
    typeof stepData.cooking_time === "number" && stepData.cooking_time > 0
      ? stepData.cooking_time
      : undefined;

  const totalTimeSeconds =
    typeof stepData.total_time_seconds === "number"
      ? stepData.total_time_seconds
      : 0;

  const totalTimeMinutes =
    totalTimeMinutesFromRecipe ?? Math.max(0, Math.floor(totalTimeSeconds / 60));

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.1 }}
    >
      <Card className="w-full bg-background_alt border-secondary/10">
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle className="text-lg">{stepData.dish_name}</CardTitle>
            <Badge className="text-xs">
              {stepList.length} steps
            </Badge>
          </div>
        </CardHeader>
        {/* Recipe image preview */}
        {stepData.image_link && (
          <div className="mx-4 mb-4 rounded-md overflow-hidden bg-gradient-to-br from-secondary/10 to-secondary/5">
            <div className="relative w-full aspect-video">
              {!imageLoaded && !imageError && (
                <Skeleton className="absolute inset-0 w-full h-full" />
              )}
              {imageError && (
                <div className="absolute inset-0 flex items-center justify-center bg-secondary/10">
                  <ImageIcon className="w-10 h-10 text-secondary/40" />
                </div>
              )}
              {!imageError && (
                <motion.img
                  src={stepData.image_link}
                  alt={stepData.dish_name || "Recipe image"}
                  className={`w-full h-full object-cover transition-opacity duration-500 ${
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
            </div>
          </div>
        )}
        <CardContent className="space-y-4 pt-0">
          {/* Steps */}
          <div className="space-y-2">
            {stepList.map((step, stepIdx) => (
              <motion.div
                key={stepIdx}
                initial={{ opacity: 0, x: -20 }}
                animate={{
                  opacity: 1,
                  x: 0,
                }}
                transition={{ delay: stepIdx * 0.05 }}
                className="p-3 rounded-lg border border-secondary/5 bg-background"
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-sm font-semibold text-primary">
                    {step.index}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-primary">{step.instruction}</p>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Total Time & Serving Info */}
          <div className="pt-3 border-t border-secondary/10 space-y-1">
            {totalTimeMinutes > 0 && (
              <p className="text-xs text-secondary">
                ⏱️ Thời gian nấu ước tính: {totalTimeMinutes} min
              </p>
            )}
            {stepData.serving_size && stepData.serving_size > 0 && (
              <p className="text-xs text-secondary">
                🍽️ Serves: {stepData.serving_size}{" "}
                {stepData.serving_size === 1 ? "person" : "people"}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default CookingStepsDisplay;

