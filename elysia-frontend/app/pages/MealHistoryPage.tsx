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
  const [currentMonth, setCurrentMonth] = useState<Date>(new Date());
  const [selectedDate, setSelectedDate] = useState<string | null>(null); // YYYY-MM-DD

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

        // Helper: format YYYY-MM-DD
        const fmtDate = (d: Date) => d.toISOString().slice(0, 10);

        // Build calendar days for the current month (array of Date or null for blanks)
        const buildMonthGrid = (month: Date) => {
          const first = new Date(month.getFullYear(), month.getMonth(), 1);
          const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
          const startWeekday = first.getDay(); // 0 (Sun) - 6
          const days: (Date | null)[] = [];
          // Fill blanks before first day
          for (let i = 0; i < startWeekday; i++) days.push(null);
          for (let d = 1; d <= last.getDate(); d++) days.push(new Date(month.getFullYear(), month.getMonth(), d));
          // Pad to complete weeks (42 cells)
          while (days.length % 7 !== 0) days.push(null);
          return days;
        };

        const monthGrid = buildMonthGrid(currentMonth);

        // Map logs by date (YYYY-MM-DD)
        const logsByDate: Record<string, any[]> = {};
        if (historyData && historyData.logs) {
          historyData.logs.forEach((log) => {
            const d = log.logged_at.slice(0, 10);
            if (!logsByDate[d]) logsByDate[d] = [] as any;
            logsByDate[d].push(log as any);
          });
        }

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

            {/* Calendar */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Button size="icon" variant="ghost" onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1))}>&lt;</Button>
                  <div className="text-sm font-medium">{currentMonth.toLocaleString(undefined, { month: 'long', year: 'numeric' })}</div>
                  <Button size="icon" variant="ghost" onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1))}>&gt;</Button>
                </div>
                <div>
                  <Button size="sm" variant={selectedDate ? "default" : "outline"} onClick={() => setSelectedDate(null)}>Show All</Button>
                </div>
              </div>

              <div className="grid grid-cols-7 gap-1 text-xs text-secondary mb-1">
                <div className="text-center">Sun</div>
                <div className="text-center">Mon</div>
                <div className="text-center">Tue</div>
                <div className="text-center">Wed</div>
                <div className="text-center">Thu</div>
                <div className="text-center">Fri</div>
                <div className="text-center">Sat</div>
              </div>

              <div className="grid grid-cols-7 gap-2">
                {monthGrid.map((d, idx) => {
                  if (!d) return <div key={idx} />;
                  const dayKey = fmtDate(d);
                  const hasLogs = !!logsByDate[dayKey] && logsByDate[dayKey].length > 0;
                  const kcal = historyData?.daily_totals?.[dayKey]?.kcal;
                  const isSelected = selectedDate === dayKey;
                  return (
                    <button
                      key={idx}
                      onClick={() => setSelectedDate(dayKey)}
                      className={`p-2 rounded-lg text-sm w-full text-left ${isSelected ? 'bg-accent/10 border border-accent' : 'hover:bg-foreground/5'} `}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{d.getDate()}</span>
                        {hasLogs && <span className="text-xs text-secondary">{kcal ? Math.round(kcal) + ' kcal' : '●'}</span>}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

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
                        {(() => {
                          // If a specific date is selected, show only that day's logs
                          if (selectedDate) {
                            const dayLogs = (logsByDate[selectedDate] || []).map((log: any) => ({
                              log_id: log.log_id,
                              logged_at: log.logged_at,
                              meal_description: log.meal_description,
                              parsed_dish: log.parsed_dish,
                              calculated_macros: log.calculated_macros,
                              calculated_micros: log.calculated_micros,
                              portion_size: log.portion_size,
                              ingredients: log.ingredients,
                            }));
                            const payload = [
                              {
                                logs: dayLogs,
                                daily_totals: selectedDate && historyData?.daily_totals ? { [selectedDate]: historyData.daily_totals[selectedDate] } : {},
                              } as any as MealHistoryPayload,
                            ];
                            return <MealHistoryDisplay history={payload} />;
                          }
                          return <MealHistoryDisplay history={getDisplayData()} />;
                        })()}
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
