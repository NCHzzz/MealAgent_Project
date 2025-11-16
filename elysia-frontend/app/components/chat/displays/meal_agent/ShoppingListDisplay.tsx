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
      const category = item.category || "Other";
      if (!grouped[category]) {
        grouped[category] = [];
      }
      grouped[category].push(item);
    });
    return grouped;
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
                          className="flex justify-between items-center text-sm py-1"
                        >
                          <span className="text-primary">{item.ingredient_name}</span>
                          <span className="text-secondary">
                            {item.quantity} {item.unit}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}

                {/* Summary */}
                {list.original_count !== undefined &&
                  list.removed_count !== undefined && (
                    <div className="pt-3 border-t border-secondary/10">
                      <p className="text-xs text-secondary">
                        Original: {list.original_count} items | Removed:{" "}
                        {list.removed_count} from pantry | Final: {list.items.length}{" "}
                        items needed
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

export default ShoppingListDisplay;

