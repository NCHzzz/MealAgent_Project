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

  const groupByCategory = (items: ShoppingListPayload["items"]) => {
    const grouped: {
      [category: string]: ShoppingListPayload["items"];
    } = {};
    items.forEach((item) => {
      // Try to infer category from ingredient name if not provided
      const category = item.category || _inferCategory(item.ingredient_name) || "Other";
      if (!grouped[category]) {
        grouped[category] = [];
      }
      grouped[category].push(item);
    });
    return grouped;
  };

  const _inferCategory = (ingredientName: string): string => {
    const name = ingredientName.toLowerCase();
    if (name.includes("chicken") || name.includes("beef") || name.includes("pork") || name.includes("fish") || name.includes("meat")) {
      return "Meat & Seafood";
    }
    if (name.includes("milk") || name.includes("cheese") || name.includes("yogurt") || name.includes("butter")) {
      return "Dairy";
    }
    if (name.includes("tomato") || name.includes("onion") || name.includes("carrot") || name.includes("lettuce") || name.includes("vegetable")) {
      return "Produce";
    }
    if (name.includes("rice") || name.includes("pasta") || name.includes("bread") || name.includes("flour")) {
      return "Grains";
    }
    if (name.includes("oil") || name.includes("vinegar") || name.includes("spice") || name.includes("salt") || name.includes("pepper")) {
      return "Pantry Staples";
    }
    return "Other";
  };

  return (
    <DisplayPagination>
      {lists.map((list, idx) => {
        const grouped = groupByCategory(list.items);

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
                  <CardTitle className="text-lg">Shopping List</CardTitle>
                  <div className="flex gap-2">
                    <Badge variant="outline" className="text-xs">
                      {list.items.length} items
                    </Badge>
                    {list.removed_count !== undefined &&
                      list.removed_count > 0 && (
                        <Badge variant="secondary" className="text-xs">
                          -{list.removed_count} from pantry
                        </Badge>
                      )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Grouped by Category */}
                {Object.entries(grouped).map(([category, items]) => (
                  <div key={category} className="space-y-2">
                    <h4 className="font-semibold text-sm text-primary capitalize">
                      {category}
                    </h4>
                    <div className="space-y-1 pl-4">
                      {items.map((item, itemIdx) => (
                        <div
                          key={itemIdx}
                          className="flex justify-between items-center text-sm py-1.5 px-2 rounded hover:bg-background/50 transition-colors"
                        >
                          <span className="text-primary flex-1">{item.ingredient_name}</span>
                          <span className="text-secondary font-medium ml-2">
                            {item.quantity.toFixed(1)} {item.unit}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}

                {/* Summary */}
                <div className="pt-3 border-t border-secondary/10 space-y-1">
                  {list.original_count !== undefined &&
                    list.removed_count !== undefined && (
                      <div className="text-xs text-secondary">
                        <span className="font-medium">Summary:</span> Original {list.original_count} items | 
                        <span className="text-green-600 dark:text-green-400"> -{list.removed_count} from pantry</span> | 
                        Final: <span className="font-semibold text-primary">{list.items.length} items needed</span>
                      </div>
                    )}
                  {list.items.length === 0 && (
                    <p className="text-xs text-green-600 dark:text-green-400">
                      ✅ All items already in pantry!
                    </p>
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

