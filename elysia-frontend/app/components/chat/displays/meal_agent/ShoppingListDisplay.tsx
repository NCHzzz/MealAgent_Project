"use client";

import React from "react";
import { motion } from "framer-motion";
import { ShoppingListPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import DisplayPagination from "../../components/DisplayPagination";

interface ShoppingListDisplayProps {
  lists: ShoppingListPayload[];
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

const ShoppingListDisplay: React.FC<ShoppingListDisplayProps> = ({
  lists,
  handleResultPayloadChange,
}) => {
  if (lists.length === 0) return null;

  const groupByCategory = (items: ShoppingListPayload["items"]) =>
    items.reduce<Record<string, ShoppingListPayload["items"]>>((acc, item) => {
      const category =
        item.category || _inferCategory(item.ingredient_name) || "Khác";
      if (!acc[category]) acc[category] = [];
      acc[category].push(item);
      return acc;
    }, {});

  const _inferCategory = (ingredientName: string): string => {
    const name = ingredientName.toLowerCase();

    // Thịt, cá, hải sản
    if (
      name.includes("chicken") ||
      name.includes("beef") ||
      name.includes("pork") ||
      name.includes("fish") ||
      name.includes("meat") ||
      name.includes("thịt") ||
      name.includes("cá") ||
      name.includes("tôm") ||
      name.includes("gà") ||
      name.includes("heo") ||
      name.includes("bò")
    ) {
      return "Thịt & Hải sản";
    }

    // Sản phẩm từ sữa
    if (
      name.includes("milk") ||
      name.includes("cheese") ||
      name.includes("yogurt") ||
      name.includes("butter") ||
      name.includes("sữa") ||
      name.includes("phô mai") ||
      name.includes("bơ")
    ) {
      return "Sữa & Phô mai";
    }

    // Rau củ quả
    if (
      name.includes("tomato") ||
      name.includes("onion") ||
      name.includes("carrot") ||
      name.includes("lettuce") ||
      name.includes("vegetable") ||
      name.includes("rau") ||
      name.includes("hành") ||
      name.includes("tỏi") ||
      name.includes("cà rốt") ||
      name.includes("bí") ||
      name.includes("ớt") ||
      name.includes("dưa") ||
      name.includes("ngô") ||
      name.includes("bông") ||
      name.includes("lá")
    ) {
      return "Rau củ & Thảo mộc";
    }

    // Tinh bột, ngũ cốc
    if (
      name.includes("rice") ||
      name.includes("pasta") ||
      name.includes("bread") ||
      name.includes("flour") ||
      name.includes("gạo") ||
      name.includes("bún") ||
      name.includes("phở") ||
      name.includes("miến") ||
      name.includes("mì") ||
      name.includes("bột mì")
    ) {
      return "Ngũ cốc & Tinh bột";
    }

    // Gia vị, nước chấm, đồ khô
    if (
      name.includes("oil") ||
      name.includes("vinegar") ||
      name.includes("spice") ||
      name.includes("salt") ||
      name.includes("pepper") ||
      name.includes("muối") ||
      name.includes("mắm") ||
      name.includes("nước mắm") ||
      name.includes("đường") ||
      name.includes("bột") ||
      name.includes("tiêu") ||
      name.includes("sa tế") ||
      name.includes("ngũ vị") ||
      name.includes("dầu")
    ) {
      return "Gia vị & Đồ khô";
    }

    return "Khác";
  };

  const formatQuantity = (quantity: number, unit: string) => {
    if (Number.isInteger(quantity)) return `${quantity} ${unit}`.trim();
    const rounded = Number(quantity.toFixed(2));
    const normalized =
      Math.abs(rounded - Math.trunc(rounded)) < 0.01
        ? Math.trunc(rounded)
        : rounded;
    return `${normalized} ${unit}`.trim();
  };

  const normalizeCategoryOrder = (grouped: Record<string, ShoppingListPayload["items"]>) =>
    Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b));

  return (
    <DisplayPagination>
      {lists.map((list, idx) => {
        const grouped =
          (list.categories && Object.keys(list.categories).length > 0
            ? list.categories
            : groupByCategory(list.items)) as Record<
            string,
            ShoppingListPayload["items"]
          >;

        return (
          <motion.div
            key={idx}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.1 }}
          >
            <Card className="w-full bg-background_alt/70 border border-secondary/20 shadow-sm">
              <CardHeader className="pb-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <CardTitle className="text-lg font-semibold text-primary">
                      Danh sách nguyên liệu cần mua
                    </CardTitle>
                    <p className="text-sm text-secondary">
                      Tự động tạo từ kế hoạch bữa ăn & kho hiện tại
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge className="text-xs border border-secondary/30 bg-transparent text-secondary">
                      {list.items.length} mục cần mua
                    </Badge>
                    {typeof list.removed_count === "number" &&
                      typeof list.original_count === "number" && (
                        <Badge className="text-xs bg-green-500/15 text-green-700 dark:text-green-300 border border-green-500/30">
                          Đã trừ {list.removed_count} mục trong kho / {list.original_count}
                        </Badge>
                      )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {normalizeCategoryOrder(grouped).map(([category, items]) => (
                    <div
                      key={category}
                      className="rounded-xl border border-secondary/10 bg-foreground_alt/40 px-3 py-3 space-y-2 shadow-[0_1px_10px_rgba(0,0,0,0.04)]"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-primary capitalize">
                            {category}
                          </span>
                          <Badge variant="outline" className="text-[11px]">
                            {items.length}
                          </Badge>
                        </div>
                      </div>
                      <div className="divide-y divide-secondary/10">
                        {items.map((item, itemIdx) => (
                          <div
                            key={itemIdx}
                            className="flex items-start justify-between gap-3 py-2"
                          >
                            <div className="flex-1 text-sm text-primary">
                              {item.ingredient_name}
                            </div>
                            <div className="text-xs font-semibold text-secondary whitespace-nowrap">
                              {formatQuantity(item.quantity, item.unit)}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex flex-wrap items-center gap-3 rounded-lg border border-secondary/20 bg-foreground_alt/50 px-3 py-2 text-xs text-secondary">
                  {typeof list.original_count === "number" &&
                    typeof list.removed_count === "number" && (
                      <span>
                        Tổng: {list.original_count} mục • Đã có trong kho:{" "}
                        {list.removed_count} • Cần mua:{" "}
                        <strong className="text-primary">{list.items.length}</strong>
                      </span>
                    )}
                  {list.items.length === 0 && (
                    <span className="text-green-600 dark:text-green-400 font-medium">
                      ✅ Bạn đã có đủ nguyên liệu trong kho!
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          </motion.div>
        );
      })}
    </DisplayPagination>
  );
};

export default ShoppingListDisplay;

