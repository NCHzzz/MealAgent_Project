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

  // Check if this is a history object with logs array (from meal_history_tool)
  const isHistoryObject = history.length > 0 && 'logs' in history[0] && Array.isArray(history[0].logs);
  
  if (isHistoryObject) {
    // Handle meal_history_tool output (has logs array and daily_totals)
    const historyData = history[0] as any;
    const logs = historyData.logs || [];
    const dailyTotals = historyData.daily_totals || {};
    
    return (
      <DisplayPagination>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Card className="w-full bg-background_alt border-secondary/10">
            <CardHeader>
              <div className="flex justify-between items-center">
                <CardTitle className="text-lg">Meal History</CardTitle>
                <Badge className="text-xs border border-secondary/20">
                  {logs.length} meal{logs.length !== 1 ? 's' : ''} | {Object.keys(dailyTotals).length} day{Object.keys(dailyTotals).length !== 1 ? 's' : ''}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Daily Totals */}
              {Object.keys(dailyTotals).length > 0 && (
                <div>
                  <h4 className="font-semibold text-sm mb-2">Daily Totals</h4>
                  <div className="space-y-2">
                    {Object.entries(dailyTotals).map(([date, totals]: [string, any]) => (
                      <div key={date} className="p-2 bg-background rounded border border-secondary/5">
                        <div className="flex justify-between items-center mb-1">
                          <span className="text-sm font-medium text-primary">{date}</span>
                          <span className="text-xs text-secondary">{formatKcal(totals.kcal || 0)}</span>
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-xs">
                          <div>
                            <span className="text-secondary">P: </span>
                            <span className="text-primary">{formatMacro(totals.protein_g || 0)}</span>
                          </div>
                          <div>
                            <span className="text-secondary">F: </span>
                            <span className="text-primary">{formatMacro(totals.fat_g || 0)}</span>
                          </div>
                          <div>
                            <span className="text-secondary">C: </span>
                            <span className="text-primary">{formatMacro(totals.carb_g || 0)}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Individual Logs */}
              {logs.length > 0 && (
                <div>
                  <h4 className="font-semibold text-sm mb-2">Meal Logs</h4>
                  <div className="space-y-2">
                    {logs.map((entry: any, idx: number) => (
                      <div key={entry.log_id || idx} className="p-3 bg-background rounded border border-secondary/5">
                        <div className="flex justify-between items-start mb-2">
                          <div className="flex-1">
                            <p className="text-sm font-medium text-primary">
                              {entry.parsed_dish || entry.meal_description || "Meal"}
                            </p>
                            <p className="text-xs text-secondary mt-1">{formatDate(entry.logged_at)}</p>
                          </div>
                          <Badge className="text-xs border border-secondary/20">
                            {formatKcal(entry.calculated_macros?.kcal || 0)}
                          </Badge>
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-xs">
                          <div>
                            <span className="text-secondary">P: </span>
                            <span className="text-primary">{formatMacro(entry.calculated_macros?.protein_g || 0)}</span>
                          </div>
                          <div>
                            <span className="text-secondary">F: </span>
                            <span className="text-primary">{formatMacro(entry.calculated_macros?.fat_g || 0)}</span>
                          </div>
                          <div>
                            <span className="text-secondary">C: </span>
                            <span className="text-primary">{formatMacro(entry.calculated_macros?.carb_g || 0)}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>
      </DisplayPagination>
    );
  }
  
  // Handle individual meal log entries
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
                <Badge className="text-xs border border-secondary/20">
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

