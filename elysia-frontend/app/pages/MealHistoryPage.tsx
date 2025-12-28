"use client";

import React, { useContext, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { SessionContext } from "../components/contexts/SessionContext";
import MealHistoryDisplay from "../components/chat/displays/meal_agent/MealHistoryDisplay";
import RecipeDetail from "../components/chat/displays/meal_agent/RecipeDetail";
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
import { getCollectionData } from "../api/getCollection";
import { MealHistoryPayload, RecipeCardPayload } from "../types/displays";
import { CollectionDataPayload } from "../types/payloads";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export default function MealHistoryPage() {
  const { id } = useContext(SessionContext);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [historyData, setHistoryData] = useState<MealHistoryResponse | null>(null);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [currentMonth, setCurrentMonth] = useState<Date>(new Date());
  const [selectedDate, setSelectedDate] = useState<string | null>(null); // YYYY-MM-DD
  const [selectedMeal, setSelectedMeal] = useState<any | null>(null);
  const [selectedRecipes, setSelectedRecipes] = useState<RecipeCardPayload[]>([]);
  const [activeRecipeIndex, setActiveRecipeIndex] = useState<number>(0);
  const [loadingRecipe, setLoadingRecipe] = useState<boolean>(false);
  const [recipeError, setRecipeError] = useState<string | null>(null);
  const [isRecipeDialogOpen, setIsRecipeDialogOpen] = useState<boolean>(false);

  const fetchMealHistory = async () => {
    if (!id) {
      setError("ID người dùng không tồn tại");
      setLoading(false);
      return;
    }

    try {
      setError(null);
      // Default: get logs from both past and near future (so future week plans still display)
      const today = new Date();
      const past = new Date(today);
      past.setDate(past.getDate() - 30);
      const future = new Date(today);
      future.setDate(future.getDate() + 30);

      const startDate = past.toISOString().slice(0, 10); // YYYY-MM-DD
      const endDate = future.toISOString().slice(0, 10); // YYYY-MM-DD

      const data = await getMealHistory(id, 30, 50, startDate, endDate);
      
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

  const buildRecipePayloadFromCollection = (
    dishName: string,
    entry: any,
    raw: any | undefined,
  ): RecipeCardPayload => {

    const baseName = dishName || entry?.parsed_dish || entry?.meal_description || "Dish";

    const macrosFromEntry = entry?.calculated_macros || {};

    const rawMacros =
      raw?.macros_per_serving ||
      raw?.macros ||
      (typeof raw?.kcal_per_serving === "number"
        ? {
            kcal: raw.kcal_per_serving,
            protein_g: raw.protein_g_per_serving ?? macrosFromEntry.protein_g,
            fat_g: raw.fat_g_per_serving ?? macrosFromEntry.fat_g,
            carb_g: raw.carb_g_per_serving ?? macrosFromEntry.carb_g,
          }
        : undefined);

    const macros_per_serving =
      rawMacros ||
      (macrosFromEntry && typeof macrosFromEntry.kcal === "number"
        ? {
            kcal: macrosFromEntry.kcal,
            protein_g: macrosFromEntry.protein_g,
            fat_g: macrosFromEntry.fat_g,
            carb_g: macrosFromEntry.carb_g,
          }
        : undefined);

    const ingredients_with_qty =
      raw?.ingredients_with_qty ||
      raw?.ingredients ||
      entry?.ingredients ||
      undefined;

    return {
      food_id:
        raw?.food_id ||
        raw?.uuid ||
        raw?.id ||
        raw?._REF_ID ||
        baseName,
      dish_name: raw?.dish_name || raw?.title || baseName,
      dish_type: raw?.dish_type,
      serving_size: raw?.serving_size,
      cooking_time: raw?.cooking_time,
      macros_per_serving,
      allergens: raw?.allergens,
      diet_type: Array.isArray(raw?.diet_type)
        ? raw.diet_type
        : raw?.diet_type
        ? [raw.diet_type]
        : undefined,
      image_link: raw?.image_link || raw?.image_url || raw?.image,
      ingredients: raw?.ingredients || entry?.ingredients,
      ingredients_with_qty,
      cooking_method_array:
        (Array.isArray(raw?.cooking_method_array)
          ? raw.cooking_method_array
          : Array.isArray(entry?.cooking_method_array)
          ? entry.cooking_method_array
          : undefined) as string[] | undefined,
    };
  };

  const handleMealClick = async (entry: any) => {
    if (!id) return;

    const baseDishText: string =
      typeof entry?.parsed_dish === "string" && entry.parsed_dish.trim().length > 0
        ? entry.parsed_dish
        : typeof entry?.meal_description === "string"
        ? entry.meal_description
        : "Dish";

    // Try to split into multiple possible dishes (e.g. "Cơm trắng, Thịt ba chỉ nướng")
    const rawParts = baseDishText
      .split(/[,;+•\-]|và|&/i)
      .map((p) => p.trim())
      .filter((p) => p.length > 0);

    const dishCandidates = rawParts.length > 1 ? rawParts : [baseDishText];

    setSelectedMeal(entry);
    setSelectedRecipes([]);
    setActiveRecipeIndex(0);
    setRecipeError(null);
    setLoadingRecipe(true);
    setIsRecipeDialogOpen(true);

    try {
      const filter_config = {
        type: "and",
        filters: [] as any[],
      };

      const results: RecipeCardPayload[] = [];

      // Fetch recipes for each candidate dish name in parallel
      const collectionResponses: (CollectionDataPayload | null)[] =
        await Promise.all(
          dishCandidates.map((name) =>
            getCollectionData(
              id,
              "Recipe",
              1,
              1,
              null,
              true,
              filter_config,
              name,
            ) as Promise<CollectionDataPayload | null>,
          ),
        );

      collectionResponses.forEach((data, idx) => {
        const raw = data?.items?.[0] as any | undefined;
        const dishName = dishCandidates[idx];
        const payload = buildRecipePayloadFromCollection(dishName, entry, raw);
        results.push(payload);
      });

      // If nothing came back from collection, still create one generic payload
      if (results.length === 0) {
        results.push(buildRecipePayloadFromCollection(baseDishText, entry, undefined));
      }

      setSelectedRecipes(results);
      setActiveRecipeIndex(0);
    } catch (e) {
      console.error("Error fetching recipe from collection:", e);
      setRecipeError("Không thể tải công thức từ bộ sưu tập Recipe");
    } finally {
      setLoadingRecipe(false);
    }
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
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45 }}
      className="w-full h-full overflow-y-auto bg-gradient-to-br from-background via-background_alt to-background_alt/30"
    >
      <div className="w-full max-w-6xl mx-auto px-4 py-10 pb-20">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-10"
        >
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="inline-flex items-center justify-center w-20 h-20 bg-gradient-to-r from-primary via-accent to-accent rounded-full mb-6 shadow-xl"
          >
            <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary via-accent to-accent mb-3"
          >
            Lịch sử bữa ăn
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="text-secondary max-w-2xl mx-auto text-base md:text-lg"
          >
            Xem lại các bữa ăn đã ghi nhận và tổng dinh dưỡng hàng ngày.
          </motion.p>
        </motion.div>

        {/* Action buttons */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="flex items-center justify-center gap-2 mb-8"
        >
          <Button size="icon" variant="outline" onClick={handleRefresh} disabled={loading || refreshing} className="h-11 w-11">
            <IoRefresh className={`h-5 w-5 ${refreshing ? "animate-spin" : ""}`} />
          </Button>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.5 }}
        >
          <Card className="shadow-xl bg-background_alt border-secondary/20 backdrop-blur-sm">
            <CardHeader className="pb-4">
              <CardTitle className="text-2xl flex items-center gap-2">
                <svg className="w-6 h-6 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
                30 ngày gần nhất
              </CardTitle>
              <CardDescription className="text-sm mt-1">Duyệt qua các bữa ăn đã ghi nhận và tổng dinh dưỡng hàng ngày.</CardDescription>
            </CardHeader>
            <CardContent>
              <Separator className="mb-6" />

              {/* Calendar */}
              <div className="mb-6">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Button 
                      size="icon" 
                      variant="outline" 
                      onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1))}
                      className="h-9 w-9"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                      </svg>
                    </Button>
                    <div className="text-base font-semibold px-4 min-w-[200px] text-center">
                      {currentMonth.toLocaleString("vi-VN", { month: 'long', year: 'numeric' })}
                    </div>
                    <Button 
                      size="icon" 
                      variant="outline" 
                      onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1))}
                      className="h-9 w-9"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </Button>
                  </div>
                  <div>
                    <Button 
                      size="sm" 
                      variant={selectedDate ? "default" : "outline"} 
                      onClick={() => setSelectedDate(null)}
                      className="bg-gradient-to-r from-accent to-accent/80 hover:from-accent/90 hover:to-accent/70"
                    >
                      Hiển thị tất cả
                    </Button>
                  </div>
                </div>

                <div className="grid grid-cols-7 gap-1 text-xs font-semibold text-secondary mb-2 px-1">
                  <div className="text-center py-2">CN</div>
                  <div className="text-center py-2">T2</div>
                  <div className="text-center py-2">T3</div>
                  <div className="text-center py-2">T4</div>
                  <div className="text-center py-2">T5</div>
                  <div className="text-center py-2">T6</div>
                  <div className="text-center py-2">T7</div>
                </div>

                <div className="grid grid-cols-7 gap-2">
                  {monthGrid.map((d, idx) => {
                    if (!d) return <div key={idx} className="aspect-square" />;
                    const dayKey = fmtDate(d);
                    const hasLogs = !!logsByDate[dayKey] && logsByDate[dayKey].length > 0;
                    const kcal = historyData?.daily_totals?.[dayKey]?.kcal;
                    const isSelected = selectedDate === dayKey;
                    const isToday = dayKey === fmtDate(new Date());
                    return (
                      <motion.button
                        key={idx}
                        onClick={() => setSelectedDate(dayKey)}
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        className={`aspect-square p-2 rounded-lg text-sm w-full text-left transition-all ${
                          isSelected 
                            ? 'bg-accent/20 border-2 border-accent shadow-lg' 
                            : isToday
                            ? 'bg-accent/10 border border-accent/30'
                            : 'hover:bg-foreground/5 border border-transparent'
                        }`}
                      >
                        <div className="flex flex-col items-start justify-between h-full">
                          <span className={`font-medium ${isToday ? 'text-accent' : ''}`}>{d.getDate()}</span>
                          {hasLogs && (
                            <span className="text-xs text-secondary mt-auto">
                              {kcal ? Math.round(kcal) + ' kcal' : '●'}
                            </span>
                          )}
                        </div>
                      </motion.button>
                    );
                  })}
                </div>
              </div>

              {loading && (
                <div className="flex w-full h-40 items-center justify-center">
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="text-center"
                  >
                    <p className="text-primary text-lg shine">Đang tải lịch sử bữa ăn...</p>
                  </motion.div>
                </div>
              )}

              {error && !loading && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex flex-col w-full items-center justify-center gap-3 py-8"
                >
                  <Card className="border-destructive/30 bg-destructive/10">
                    <CardContent className="pt-6">
                      <p className="text-destructive text-base flex items-center gap-2">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        {error}
                      </p>
                    </CardContent>
                  </Card>
                  <Button onClick={handleRefresh} variant="outline" size="sm" className="gap-2">
                    <IoRefresh className="h-4 w-4" />
                    Thử lại
                  </Button>
                </motion.div>
              )}

              {!loading && !error && historyData && (
                <div className="flex flex-col w-full">
                  {historyData.total_logs === 0 ? (
                    <motion.div
                      initial={{ scale: 0.9, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      className="flex flex-col items-center justify-center w-full py-16"
                    >
                      <div className="inline-flex items-center justify-center w-16 h-16 bg-secondary/10 rounded-full mb-4">
                        <svg className="w-8 h-8 text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                      </div>
                      <p className="text-secondary text-lg">Không tìm thấy bữa ăn nào trong khoảng thời gian đã chọn.</p>
                    </motion.div>
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
                              return (
                                <MealHistoryDisplay
                                  history={payload}
                                  onMealClick={handleMealClick}
                                />
                              );
                            }
                            return (
                              <MealHistoryDisplay
                                history={getDisplayData()}
                                onMealClick={handleMealClick}
                              />
                            );
                          })()}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>

        {/* Recipe detail modal */}
        <Dialog
          open={isRecipeDialogOpen}
          onOpenChange={(open) => {
            setIsRecipeDialogOpen(open);
            if (!open) {
              setSelectedMeal(null);
              setSelectedRecipes([]);
              setActiveRecipeIndex(0);
              setRecipeError(null);
              setLoadingRecipe(false);
            }
          }}
        >
          <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto bg-background_alt border-secondary/20">
            <DialogHeader>
              <DialogTitle className="text-lg md:text-2xl">
                {selectedMeal?.parsed_dish ||
                  selectedMeal?.meal_description ||
                  "Dish Details"}
              </DialogTitle>
            </DialogHeader>

            {loadingRecipe && (
              <p className="text-sm text-secondary">
                Đang tải nguyên liệu và công thức từ bộ sưu tập...
              </p>
            )}

            {recipeError && !loadingRecipe && (
              <p className="text-sm text-destructive mb-2">{recipeError}</p>
            )}

            {selectedRecipes.length > 1 && !loadingRecipe && (
              <div className="mb-4 flex flex-wrap gap-2">
                {selectedRecipes.map((r, idx) => (
                  <Button
                    key={r.food_id + idx}
                    size="sm"
                    variant={idx === activeRecipeIndex ? "default" : "outline"}
                    onClick={() => setActiveRecipeIndex(idx)}
                    className="text-xs md:text-sm"
                  >
                    {r.dish_name}
                  </Button>
                ))}
              </div>
            )}

            {selectedRecipes[activeRecipeIndex] && !loadingRecipe && (
              <RecipeDetail recipe={selectedRecipes[activeRecipeIndex]} />
            )}
          </DialogContent>
        </Dialog>
      </div>
    </motion.div>
  );
}
