"use client";

import React, { useContext, useEffect, useState } from "react";

import { SessionContext } from "../components/contexts/SessionContext";
import MealHistoryDisplay from "../components/chat/displays/meal_agent/MealHistoryDisplay";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
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
    <div className="flex flex-col w-full h-full items-center justify-start gap-3">
      <div className="flex w-full justify-between items-center lg:sticky z-20 top-0 lg:p-0 p-4 gap-5 bg-background">
        <div className="flex flex-col gap-1">
          <p className="text-primary text-lg font-semibold">
            Lịch sử bữa ăn (30 ngày gần đây)
          </p>
          <p className="text-secondary text-xs">
            Trang này truy vấn trực tiếp từ database để hiển thị log bữa ăn của bạn.
          </p>
        </div>
        <Button
          size="icon"
          variant="outline"
          onClick={handleRefresh}
          disabled={loading || refreshing}
        >
          <IoRefresh className={refreshing ? "animate-spin" : ""} />
        </Button>
      </div>

      <Separator className="w-full" />

      {loading && (
        <div className="flex w-full h-full justify-center items-center">
          <p className="text-primary text-xl shine">
            Đang tải lịch sử bữa ăn...
          </p>
        </div>
      )}

      {error && !loading && (
        <div className="flex flex-col w-full items-center justify-center gap-3 p-8">
          <p className="text-destructive text-lg">{error}</p>
          <Button onClick={handleRefresh} variant="outline">
            Thử lại
          </Button>
        </div>
      )}

      {!loading && !error && historyData && (
        <div className="flex flex-col w-full max-h-[calc(100vh-120px)] overflow-y-auto justify-center items-center">
          <div className="flex flex-col w-full md:w-[60vw] lg:w-[40vw]">
            {historyData.total_logs === 0 ? (
              <div className="flex flex-col items-center justify-center w-full h-full gap-3 p-8">
                <p className="text-primary text-sm">
                  Không có dữ liệu bữa ăn trong khoảng thời gian này.
                </p>
              </div>
            ) : (
              <MealHistoryDisplay history={getDisplayData()} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
