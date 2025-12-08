"use client";

import React, { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { MealHistoryPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { IoChevronDown, IoChevronForward } from "react-icons/io5";
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

  const formatDateTime = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString("vi-VN", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString("vi-VN", {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  const parseNum = (v: any, fallback = 0) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };

  // Check if this is a history object with logs array (from meal_history_tool)
  const isHistoryObject = history.length > 0 && 'logs' in history[0] && Array.isArray(history[0].logs);
  
  // Grouped per day to help scanning
  const grouped = useMemo(() => {
    if (!isHistoryObject) return [];
    const historyData = history[0] as any;
    const logs = historyData.logs || [];
    const dailyTotals = historyData.daily_totals || {};

    const map: Record<string, { date: string; meals: any[]; totals: any }> = {};
    logs.forEach((entry: any) => {
      const dateKey = (entry.logged_at || "").slice(0, 10);
      if (!map[dateKey]) {
        map[dateKey] = { date: dateKey, meals: [], totals: dailyTotals?.[dateKey] || {} };
      }
      map[dateKey].meals.push(entry);
    });

    const buckets = Object.values(map).map((bucket) => {
      bucket.meals.sort(
        (a, b) => new Date(b.logged_at || 0).getTime() - new Date(a.logged_at || 0).getTime()
      );
      return bucket;
    });

    buckets.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    return buckets;
  }, [history, isHistoryObject]);

  const [openDays, setOpenDays] = useState<Record<string, boolean>>({});
  const toggleDay = (date: string, idx: number) =>
    setOpenDays((prev) => {
      const initial = idx < 3; // open first 3 by default
      const current = prev[date] ?? initial;
      return { ...prev, [date]: !current };
    });

  // Group days into 7-day modules (weeks). Week 0 = most recent 7 days.
  const weeks = useMemo(() => {
    const out: {
      label: string;
      days: typeof grouped;
      totals: { kcal: number; protein_g: number; fat_g: number; carb_g: number };
    }[] = [];
    if (!grouped.length) return out;
    const days = [...grouped];
    for (let i = 0; i < days.length; i += 7) {
      const slice = days.slice(i, i + 7);
      const first = slice[0]?.date;
      const last = slice[slice.length - 1]?.date;
      const label =
        slice.length === 1
          ? formatDate(first)
          : `${formatDate(first)} → ${formatDate(last)}`;
      const totals = slice.reduce(
        (acc, d) => {
          acc.kcal += parseNum(d.totals?.kcal);
          acc.protein_g += parseNum(d.totals?.protein_g);
          acc.fat_g += parseNum(d.totals?.fat_g);
          acc.carb_g += parseNum(d.totals?.carb_g);
          return acc;
        },
        { kcal: 0, protein_g: 0, fat_g: 0, carb_g: 0 }
      );
      out.push({ label, days: slice, totals });
    }
    return out;
  }, [grouped]);

  const [selectedWeek, setSelectedWeek] = useState<number>(0);
  const selectedWeekData = weeks[Math.min(selectedWeek, Math.max(weeks.length - 1, 0))] ?? null;

  if (isHistoryObject) {
    const historyData = history[0] as any;
    const totalDays = grouped.length;
    const totalMeals = historyData.logs?.length || 0;
    const totalKcal = grouped.reduce(
      (sum, b) => sum + parseNum(b.totals?.kcal),
      0
    );
    const avgKcalPerDay = totalDays > 0 ? totalKcal / totalDays : 0;

    return (
      <DisplayPagination>
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="w-full bg-background_alt border-secondary/10 shadow-lg">
            <CardHeader>
              <div className="flex justify-between items-center">
                <CardTitle className="text-lg">Lịch sử bữa ăn</CardTitle>
                <Badge className="text-xs border border-secondary/20">
                  {totalMeals} bữa · {totalDays} ngày
                </Badge>
              </div>
              <div className="flex gap-2 text-xs text-secondary mt-2">
                <span>
                  Tổng kcal: <span className="text-primary font-medium">{formatKcal(totalKcal)}</span>
                </span>
                <Separator orientation="vertical" className="h-4 bg-secondary/40" />
                <span>
                  Trung bình/ngày:{" "}
                  <span className="text-primary font-medium">{formatKcal(avgKcalPerDay)}</span>
                </span>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Quick navigation by week (sticky on desktop) */}
              {weeks.length > 1 && (
                <div className="sticky top-0 z-10 bg-background_alt/80 backdrop-blur supports-[backdrop-filter]:backdrop-blur-md py-2 border border-secondary/10 rounded-md shadow-sm">
                  <div className="flex flex-wrap gap-2">
                    {weeks.map((w, idx) => (
                      <Button
                        key={w.label}
                        size="sm"
                        variant={idx === selectedWeek ? "default" : "outline"}
                        onClick={() => setSelectedWeek(idx)}
                        className="flex items-center gap-2"
                      >
                        <span>Tuần {idx + 1}</span>
                        <span className="text-[11px] text-muted-foreground">
                          {w.label}
                        </span>
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              {/* Selected week summary */}
              {selectedWeekData && (
                <div className="rounded-lg border border-secondary/15 bg-background p-3">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-primary">
                        Tuần {selectedWeek + 1}
                      </span>
                      <span className="text-xs text-secondary">{selectedWeekData.label}</span>
                    </div>
                    <div className="grid grid-cols-4 gap-2 text-[11px] text-primary">
                      <div className="px-2 py-1 rounded bg-secondary/10">
                        Kcal: {formatKcal(selectedWeekData.totals.kcal)}
                      </div>
                      <div className="px-2 py-1 rounded bg-secondary/10">
                        P: {formatMacro(selectedWeekData.totals.protein_g)}
                      </div>
                      <div className="px-2 py-1 rounded bg-secondary/10">
                        F: {formatMacro(selectedWeekData.totals.fat_g)}
                      </div>
                      <div className="px-2 py-1 rounded bg-secondary/10">
                        C: {formatMacro(selectedWeekData.totals.carb_g)}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Days within selected week */}
              {selectedWeekData && (
                <div className="space-y-3">
                  {selectedWeekData.days.map(({ date, meals, totals }, idx) => {
                    const isOpen = openDays[date] ?? (selectedWeek === 0 && idx < 3);
                    return (
                      <div
                        key={date}
                        className="rounded-lg border border-secondary/10 bg-background_alt p-3 space-y-3"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-7 w-7 text-secondary"
                              onClick={() => setOpenDays((prev) => ({ ...prev, [date]: !isOpen }))}
                            >
                              {isOpen ? <IoChevronDown /> : <IoChevronForward />}
                            </Button>
                            <div className="flex flex-col">
                              <span className="text-sm font-semibold text-primary">
                                {formatDate(date)}
                              </span>
                              <span className="text-xs text-secondary">
                                {meals.length} bữa · {formatKcal(parseNum(totals.kcal))}
                              </span>
                            </div>
                          </div>
                                <div className="grid grid-cols-4 gap-2 text-[11px] text-primary">
                            <div className="px-2 py-1 rounded bg-secondary/10">
                              Kcal: {formatKcal(parseNum(totals.kcal))}
                            </div>
                            <div className="px-2 py-1 rounded bg-secondary/10">
                              P: {formatMacro(parseNum(totals.protein_g))}
                            </div>
                            <div className="px-2 py-1 rounded bg-secondary/10">
                              F: {formatMacro(parseNum(totals.fat_g))}
                            </div>
                            <div className="px-2 py-1 rounded bg-secondary/10">
                              C: {formatMacro(parseNum(totals.carb_g))}
                            </div>
                          </div>
                        </div>

                        {isOpen && (
                          <div className="space-y-2">
                            {meals.map((entry: any, mealIdx: number) => (
                              <div
                                key={entry.log_id || `${date}-${mealIdx}`}
                                className="p-3 rounded border border-secondary/10 bg-background"
                              >
                              <div className="flex justify-between items-start gap-3">
                                  <div className="flex-1">
                                    <p className="text-sm font-medium text-primary">
                                      {entry.parsed_dish || entry.meal_description || "Bữa ăn"}
                                    </p>
                                    <p className="text-xs text-secondary mt-1">
                                      {formatDateTime(entry.logged_at)}
                                    </p>
                                  </div>
                                <div className="flex flex-col items-end gap-1 text-[11px] text-primary">
                                  <Badge className="text-xs border border-secondary/20">
                                    {formatKcal(entry.calculated_macros?.kcal || 0)}
                                  </Badge>
                                  <div className="flex gap-2 text-secondary">
                                    <span>P {formatMacro(parseNum(entry.calculated_macros?.protein_g))}</span>
                                    <span>F {formatMacro(parseNum(entry.calculated_macros?.fat_g))}</span>
                                    <span>C {formatMacro(parseNum(entry.calculated_macros?.carb_g))}</span>
                                  </div>
                                </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
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

