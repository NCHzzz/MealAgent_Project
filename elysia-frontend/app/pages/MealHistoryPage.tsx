"use client";

import React, { useContext, useEffect, useState } from "react";

import { SessionContext } from "../components/contexts/SessionContext";
import MealHistoryDisplay from "../components/chat/displays/meal_agent/MealHistoryDisplay";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { IoRefresh } from "react-icons/io5";
import { getMealHistory, MealHistoryResponse } from "../api/getMealHistory";
import { MealHistoryPayload } from "../types/displays";

export default function MealHistoryPage() {
  const { id } = useContext(SessionContext);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [historyData, setHistoryData] = useState<MealHistoryResponse | null>(null);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  const fetchMealHistory = async () => {
    if (!id) {
      setError("User ID không tồn tại");
      setLoading(false);
      return;
    }

    try {
      setError(null);
      const data = await getMealHistory(id, 30, 50);
      
      if (data) {
        setHistoryData(data);
      } else {
        setError("Không thể tải lịch sử bữa ăn");
      }
    } catch (err) {
      console.error("Error fetching meal history:", err);
      setError("Đã xảy ra lỗi khi tải lịch sử bữa ăn");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchMealHistory();
  }, [id]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchMealHistory();
  };

  // Convert API response to format expected by MealHistoryDisplay
  const getDisplayData = (): MealHistoryPayload[] => {
    if (!historyData || !historyData.logs || historyData.logs.length === 0) {
      return [];
    }

    // Return in the format that MealHistoryDisplay expects (with logs array and daily_totals)
    // The component checks for history[0].logs and history[0].daily_totals
    return [
      {
        logs: historyData.logs.map((log) => ({
          log_id: log.log_id,
          logged_at: log.logged_at,
          meal_description: log.meal_description,
          parsed_dish: log.parsed_dish,
          calculated_macros: log.calculated_macros,
          calculated_micros: log.calculated_micros,
          portion_size: log.portion_size,
          ingredients: log.ingredients,
        })),
        daily_totals: historyData.daily_totals,
      } as any as MealHistoryPayload,
    ];
  };

  return (
    <div className="w-full">
      <div className="container mx-auto px-4 py-8 max-w-6xl">
        <div className="flex items-center justify-between gap-4 mb-6">
          <div className="flex-1">
            <h1 className="text-3xl md:text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-accent mb-2">Meal History</h1>
          </div>

          <div className="flex items-center gap-2">
            <Button size="icon" variant="outline" onClick={handleRefresh} disabled={loading || refreshing}>
              <IoRefresh className={refreshing ? "animate-spin" : ""} />
            </Button>
          </div>
        </div>

        <Card className="bg-background_alt border-secondary/10 shadow-lg">
          <CardHeader>
            <CardTitle>Last 30 days</CardTitle>
            <CardDescription>Browse your logged meals and daily macro totals.</CardDescription>
          </CardHeader>
          <CardContent>
            <Separator className="mb-4" />

            {loading && (
              <div className="flex w-full h-40 items-center justify-center">
                <p className="text-primary text-lg shine">Loading meal history...</p>
              </div>
            )}

            {error && !loading && (
              <div className="flex flex-col w-full items-center justify-center gap-3 py-8">
                <p className="text-destructive text-base">{error}</p>
                <Button onClick={handleRefresh} variant="outline" size="sm">Retry</Button>
              </div>
            )}

            {!loading && !error && historyData && (
              <div className="flex flex-col w-full">
                {historyData.total_logs === 0 ? (
                  <div className="flex flex-col items-center justify-center w-full py-12">
                    <p className="text-primary text-sm">No meal logs found for the selected period.</p>
                  </div>
                ) : (
                  <div className="w-full">
                    <div className="max-h-[60vh] overflow-y-auto px-2">
                      <div className="mx-auto w-full max-w-3xl">
                        <MealHistoryDisplay history={getDisplayData()} />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
