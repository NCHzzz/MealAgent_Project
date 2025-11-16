"use client";

import React from "react";
import { motion } from "framer-motion";
import { MealHistoryPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import DisplayPagination from "../../components/DisplayPagination";

interface MealHistoryDisplayProps {
  history: MealHistoryPayload[];
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

const MealHistoryDisplay: React.FC<MealHistoryDisplayProps> = ({
  history,
  handleResultPayloadChange,
}) => {
  if (history.length === 0) return null;

  const formatMacro = (value: number, unit: string = "g") => {
    return `${value.toFixed(1)}${unit}`;
  };

  const formatKcal = (value: number) => {
    return `${value.toFixed(0)} kcal`;
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <DisplayPagination>
      {history.map((entry, idx) => (
        <motion.div
          key={entry.log_id || idx}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: idx * 0.1 }}
        >
          <Card className="w-full bg-background_alt border-secondary/10">
            <CardHeader>
              <div className="flex justify-between items-center">
                <CardTitle className="text-lg">
                  {entry.parsed_dish || "Meal Log"}
                </CardTitle>
                <Badge variant="outline" className="text-xs">
                  {formatDate(entry.logged_at)}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* Original Description */}
              <div>
                <p className="text-xs text-secondary mb-1">Description</p>
                <p className="text-sm text-primary">{entry.meal_description}</p>
              </div>

              {/* Macros */}
              <div>
                <p className="text-xs text-secondary mb-1">Nutrition</p>
                <div className="grid grid-cols-4 gap-2 text-sm">
                  <div>
                    <p className="text-secondary text-xs">Calories</p>
                    <p className="font-semibold text-primary">
                      {formatKcal(entry.calculated_macros.kcal)}
                    </p>
                  </div>
                  <div>
                    <p className="text-secondary text-xs">Protein</p>
                    <p className="font-semibold text-primary">
                      {formatMacro(entry.calculated_macros.protein_g)}
                    </p>
                  </div>
                  <div>
                    <p className="text-secondary text-xs">Fat</p>
                    <p className="font-semibold text-primary">
                      {formatMacro(entry.calculated_macros.fat_g)}
                    </p>
                  </div>
                  <div>
                    <p className="text-secondary text-xs">Carbs</p>
                    <p className="font-semibold text-primary">
                      {formatMacro(entry.calculated_macros.carb_g)}
                    </p>
                  </div>
                </div>
              </div>

              {/* Portion Size */}
              {entry.portion_size && entry.portion_size !== 1 && (
                <div>
                  <p className="text-xs text-secondary">
                    Portion: {entry.portion_size}x serving
                    {entry.portion_size !== 1 ? "s" : ""}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>
      ))}
    </DisplayPagination>
  );
};

export default MealHistoryDisplay;

