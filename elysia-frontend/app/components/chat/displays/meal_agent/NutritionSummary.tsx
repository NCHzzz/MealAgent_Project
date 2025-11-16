"use client";

import React from "react";
import { motion } from "framer-motion";
import { NutritionSummaryPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import DisplayPagination from "../../components/DisplayPagination";

interface NutritionSummaryProps {
  summaries: NutritionSummaryPayload[];
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

const NutritionSummary: React.FC<NutritionSummaryProps> = ({
  summaries,
  handleResultPayloadChange,
}) => {
  if (summaries.length === 0) return null;

  const formatMacro = (value: number, unit: string = "g") => {
    return `${value.toFixed(1)}${unit}`;
  };

  const formatKcal = (value: number) => {
    return `${value.toFixed(0)} kcal`;
  };

  return (
    <DisplayPagination>
      {summaries.map((summary, idx) => {
        // Prepare data for macro bar chart
        const macroData = [
          {
            name: "Protein",
            actual: summary.total_macros.protein_g,
            target: summary.targets?.protein_g || 0,
          },
          {
            name: "Fat",
            actual: summary.total_macros.fat_g,
            target: summary.targets?.fat_g || 0,
          },
          {
            name: "Carbs",
            actual: summary.total_macros.carb_g,
            target: summary.targets?.carb_g || 0,
          },
        ];

        return (
          <motion.div
            key={idx}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.1 }}
          >
            <Card className="w-full bg-background_alt border-secondary/10">
              <CardHeader>
                <div className="flex justify-between items-center">
                  <CardTitle className="text-lg">Nutrition Summary</CardTitle>
                  {summary.validation && (
                    <Badge
                      variant={summary.validation.valid ? "default" : "destructive"}
                      className="text-xs"
                    >
                      {summary.validation.valid ? "On Target" : "Issues"}
                    </Badge>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Total Macros */}
                <div>
                  <h4 className="font-semibold text-sm mb-2">Total Macros</h4>
                  <div className="grid grid-cols-4 gap-2 text-sm">
                    <div>
                      <p className="text-secondary text-xs">Calories</p>
                      <p className="font-semibold text-primary">
                        {formatKcal(summary.total_macros.kcal)}
                      </p>
                      {summary.targets && (
                        <p className="text-xs text-secondary">
                          Target: {formatKcal(summary.targets.tdee_kcal)}
                        </p>
                      )}
                    </div>
                    <div>
                      <p className="text-secondary text-xs">Protein</p>
                      <p className="font-semibold text-primary">
                        {formatMacro(summary.total_macros.protein_g)}
                      </p>
                      {summary.targets && (
                        <p className="text-xs text-secondary">
                          Target: {formatMacro(summary.targets.protein_g)}
                        </p>
                      )}
                    </div>
                    <div>
                      <p className="text-secondary text-xs">Fat</p>
                      <p className="font-semibold text-primary">
                        {formatMacro(summary.total_macros.fat_g)}
                      </p>
                      {summary.targets && (
                        <p className="text-xs text-secondary">
                          Target: {formatMacro(summary.targets.fat_g)}
                        </p>
                      )}
                    </div>
                    <div>
                      <p className="text-secondary text-xs">Carbs</p>
                      <p className="font-semibold text-primary">
                        {formatMacro(summary.total_macros.carb_g)}
                      </p>
                      {summary.targets && (
                        <p className="text-xs text-secondary">
                          Target: {formatMacro(summary.targets.carb_g)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>

                {/* Macro Bar Chart */}
                {summary.targets && (
                  <div>
                    <h4 className="font-semibold text-sm mb-2">Macro Comparison</h4>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={macroData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="name" />
                        <YAxis />
                        <Tooltip />
                        <Legend />
                        <Bar dataKey="actual" fill="#8884d8" name="Actual" />
                        <Bar dataKey="target" fill="#82ca9d" name="Target" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* Micronutrients Table */}
                {summary.micronutrients &&
                  Object.keys(summary.micronutrients).length > 0 && (
                    <div>
                      <h4 className="font-semibold text-sm mb-2">Micronutrients</h4>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-secondary/10">
                              <th className="text-left py-2 text-secondary">Nutrient</th>
                              <th className="text-right py-2 text-secondary">Total</th>
                              {summary.micronutrients[
                                Object.keys(summary.micronutrients)[0]
                              ]?.target && (
                                <th className="text-right py-2 text-secondary">
                                  Target
                                </th>
                              )}
                              <th className="text-right py-2 text-secondary">Unit</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(summary.micronutrients).map(
                              ([nutrient, data]) => (
                                <tr
                                  key={nutrient}
                                  className="border-b border-secondary/5"
                                >
                                  <td className="py-2 text-primary capitalize">
                                    {nutrient.replace(/_/g, " ")}
                                  </td>
                                  <td className="py-2 text-right text-primary">
                                    {data.total.toFixed(1)}
                                  </td>
                                  {data.target !== undefined && (
                                    <td className="py-2 text-right text-secondary">
                                      {data.target.toFixed(1)}
                                    </td>
                                  )}
                                  <td className="py-2 text-right text-secondary text-xs">
                                    {data.unit}
                                  </td>
                                </tr>
                              )
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                {/* Validation Warnings */}
                {summary.validation && !summary.validation.valid && (
                  <div className="pt-3 border-t border-secondary/10">
                    <p className="text-xs text-destructive">
                      ⚠ Nutrition targets not met. Check violations and warnings.
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>
        );
      })}
    </DisplayPagination>
  );
};

export default NutritionSummary;

