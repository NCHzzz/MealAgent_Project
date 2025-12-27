"use client";

import React, { useContext, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SessionContext } from "../components/contexts/SessionContext";
import { AuthContext } from "../components/contexts/AuthContext";
import {
  getShoppingLists,
  createShoppingItems,
  updateShoppingItems,
  deleteShoppingItems,
  togglePurchased,
  ShoppingItem,
  ShoppingList,
} from "../api/shopping";
import { IoRefresh, IoAdd, IoTrash, IoCreate, IoCheckmarkCircle, IoCheckmarkCircleOutline } from "react-icons/io5";
import { Badge } from "@/components/ui/badge";

const ShoppingListPage: React.FC = () => {
  const { id } = useContext(SessionContext);
  const { isAuthenticated } = useContext(AuthContext);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lists, setLists] = useState<ShoppingList[]>([]);
  const [selectedListId, setSelectedListId] = useState<string | null>(null);
  const [items, setItems] = useState<ShoppingItem[]>([]);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [isDialogOpen, setIsDialogOpen] = useState<boolean>(false);
  const [editingItem, setEditingItem] = useState<ShoppingItem | null>(null);
  const [formData, setFormData] = useState<Omit<ShoppingItem, "list_id">>({
    ingredient_name: "",
    quantity: 0,
    unit: "g",
    category: "general",
    purchased: false,
  });

  const fetchShoppingLists = async () => {
    if (!id) {
      setError("User ID does not exist");
      setLoading(false);
      return;
    }

    try {
      setError(null);
      const data = await getShoppingLists(id);
      
      if (data) {
        if (data.lists && data.lists.length > 0) {
          setLists(data.lists);
          // Select first list by default
          if (!selectedListId && data.lists[0].list_id) {
            setSelectedListId(data.lists[0].list_id);
            setItems(data.lists[0].items || []);
          } else if (selectedListId) {
            const selectedList = data.lists.find(l => l.list_id === selectedListId);
            if (selectedList) {
              setItems(selectedList.items || []);
            }
          }
        } else {
          setLists([]);
          setItems([]);
        }
      } else {
        setError("Unable to load shopping list data");
      }
    } catch (err) {
      console.error("Error fetching shopping lists:", err);
      setError("An error occurred while loading shopping list data");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated && id) {
      fetchShoppingLists();
    }
  }, [id, isAuthenticated]);

  useEffect(() => {
    if (selectedListId && lists.length > 0) {
      const selectedList = lists.find(l => l.list_id === selectedListId);
      if (selectedList) {
        setItems(selectedList.items || []);
      }
    }
  }, [selectedListId, lists]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchShoppingLists();
  };

  const handleListChange = (listId: string) => {
    setSelectedListId(listId);
    const selectedList = lists.find(l => l.list_id === listId);
    if (selectedList) {
      setItems(selectedList.items || []);
    }
  };

  const handleAddItem = () => {
    if (!selectedListId) {
      setError("Please select a shopping list first");
      return;
    }
    setEditingItem(null);
    setFormData({
      ingredient_name: "",
      quantity: 0,
      unit: "g",
      category: "general",
      purchased: false,
    });
    setIsDialogOpen(true);
  };

  const handleEditItem = (item: ShoppingItem) => {
    setEditingItem(item);
    setFormData({
      ingredient_name: item.ingredient_name,
      quantity: item.quantity,
      unit: item.unit,
      category: item.category || "general",
      purchased: item.purchased,
    });
    setIsDialogOpen(true);
  };

  const handleDeleteItem = async (item: ShoppingItem) => {
    if (!id || !selectedListId || !confirm(`Are you sure you want to delete "${item.ingredient_name}"?`)) {
      return;
    }

    try {
      const result = await deleteShoppingItems(id, selectedListId, [item]);
      if (result) {
        await fetchShoppingLists();
      } else {
        setError("Unable to delete item");
      }
    } catch (err) {
      console.error("Error deleting item:", err);
      setError("An error occurred while deleting item");
    }
  };

  const handleTogglePurchased = async (item: ShoppingItem) => {
    if (!id || !selectedListId) {
      return;
    }

    try {
      const result = await togglePurchased(id, selectedListId, [item]);
      if (result) {
        await fetchShoppingLists();
      }
    } catch (err) {
      console.error("Error toggling purchased:", err);
      setError("An error occurred while updating status");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id || !selectedListId) return;

    if (!formData.ingredient_name.trim()) {
      setError("Ingredient name cannot be empty");
      return;
    }

    if (formData.quantity <= 0) {
      setError("Quantity must be greater than 0");
      return;
    }

    try {
      setError(null);
      let result;
      
      const itemData: ShoppingItem = {
        list_id: selectedListId,
        ...formData,
      };
      
      if (editingItem) {
        // Update existing item
        result = await updateShoppingItems(id, selectedListId, [itemData]);
      } else {
        // Create new item
        result = await createShoppingItems(id, selectedListId, [itemData]);
      }

      if (result) {
        setIsDialogOpen(false);
        await fetchShoppingLists();
      } else {
        setError(editingItem ? "Unable to update item" : "Unable to add item");
      }
    } catch (err) {
      console.error("Error saving item:", err);
      setError("An error occurred while saving item");
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-secondary">
          Please log in to manage your shopping lists.
        </p>
      </div>
    );
  }

  if (loading && lists.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-secondary">Loading shopping lists...</p>
      </div>
    );
  }

  const selectedList = lists.find(l => l.list_id === selectedListId);
  const purchasedCount = items.filter(i => i.purchased).length;
  const remainingCount = items.length - purchasedCount;

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
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z" />
            </svg>
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary via-accent to-accent mb-3"
          >
            Shopping List
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="text-secondary max-w-2xl mx-auto text-base md:text-lg"
          >
            Manage the list of ingredients you need to buy for your meals. Mark items as purchased when you complete your shopping.
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
          <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
            <DialogTrigger asChild>
              <Button onClick={handleAddItem} className="gap-2 h-11 px-6 bg-gradient-to-r from-accent to-accent/80 hover:from-accent/90 hover:to-accent/70 shadow-lg text-white font-medium" disabled={!selectedListId}>
                <IoAdd className="h-5 w-5" />
                Add Item
              </Button>
            </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{editingItem ? "Edit Item" : "Add New Item"}</DialogTitle>
                  <DialogDescription>
                    {editingItem ? "Update item information in the list" : "Add a new item to your shopping list"}
                  </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div>
                    <Label>Ingredient Name *</Label>
                    <Input
                      value={formData.ingredient_name}
                      onChange={(e) => setFormData({ ...formData, ingredient_name: e.target.value })}
                      placeholder="e.g., Rice, Chicken, Vegetables..."
                      required
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label>Quantity *</Label>
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        value={formData.quantity || ""}
                        onChange={(e) => setFormData({ ...formData, quantity: parseFloat(e.target.value) || 0 })}
                        required
                      />
                    </div>
                    <div>
                      <Label>Unit *</Label>
                      <Input
                        value={formData.unit}
                        onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
                        placeholder="g, kg, ml, l..."
                        required
                      />
                    </div>
                  </div>
                  <div>
                    <Label>Category</Label>
                    <Select
                      value={formData.category}
                      onValueChange={(value) => setFormData({ ...formData, category: value })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select category" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="general">Other</SelectItem>
                        <SelectItem value="Thịt & Hải sản">Meat & Seafood</SelectItem>
                        <SelectItem value="Sữa & Phô mai">Dairy & Cheese</SelectItem>
                        <SelectItem value="Rau củ & Thảo mộc">Vegetables & Herbs</SelectItem>
                        <SelectItem value="Ngũ cốc & Tinh bột">Grains & Starches</SelectItem>
                        <SelectItem value="Gia vị & Đồ khô">Spices & Dried Goods</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {error && (
                    <p className="text-sm text-destructive">{error}</p>
                  )}
                  <div className="flex justify-end gap-2">
                    <Button type="button" variant="outline" onClick={() => setIsDialogOpen(false)}>
                      Cancel
                    </Button>
                    <Button type="submit">
                      {editingItem ? "Update" : "Add"}
                    </Button>
                  </div>
                </form>
              </DialogContent>
            </Dialog>
        </motion.div>

        {/* List Selector */}
        {lists.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.5 }}
          >
            <Card className="mb-6 shadow-xl bg-background_alt border-secondary/20 backdrop-blur-sm">
              <CardContent className="pt-6">
                <div className="flex flex-col md:flex-row md:items-center gap-4">
                  <Label className="text-sm font-semibold">Select list:</Label>
                <Select value={selectedListId || ""} onValueChange={handleListChange}>
                  <SelectTrigger className="w-[300px]">
                    <SelectValue placeholder="Select list" />
                  </SelectTrigger>
                  <SelectContent>
                    {lists.map((list) => {
                      // Format plan date for display - prioritize plan_start_date
                      let dateLabel = "";
                      let dateForSorting = null;
                      
                      if (list.plan_start_date) {
                        try {
                          const planDate = new Date(list.plan_start_date);
                          if (!isNaN(planDate.getTime())) {
                            dateForSorting = planDate;
                            // Format: "Plan: Day, MM/DD/YYYY"
                            const dayName = planDate.toLocaleDateString("en-US", { weekday: "long" });
                            const dateStr = planDate.toLocaleDateString("en-US");
                            dateLabel = ` - Plan: ${dayName}, ${dateStr}`;
                          }
                        } catch (e) {
                          console.warn("Invalid plan_start_date:", list.plan_start_date, e);
                        }
                      }
                      
                      // Fallback to created_at if no plan_start_date
                      if (!dateLabel && list.created_at) {
                        try {
                          const createdDate = new Date(list.created_at);
                          if (!isNaN(createdDate.getTime())) {
                            dateForSorting = createdDate;
                            dateLabel = ` - Created: ${createdDate.toLocaleDateString("en-US")}`;
                          }
                        } catch (e) {
                          console.warn("Invalid created_at:", list.created_at, e);
                        }
                      }
                      
                      // Short plan_id for display
                      const planIdShort = list.plan_id 
                        ? list.plan_id.length > 20 
                          ? `${list.plan_id.substring(0, 20)}...` 
                          : list.plan_id
                        : "No plan";
                      
                      return (
                        <SelectItem key={list.list_id} value={list.list_id || ""}>
                          {planIdShort}{dateLabel}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                {selectedList && (
                  <div className="flex flex-wrap gap-2">
                    {selectedList.plan_start_date && (() => {
                      try {
                        const planDate = new Date(selectedList.plan_start_date);
                        if (!isNaN(planDate.getTime())) {
                          const today = new Date();
                          today.setHours(0, 0, 0, 0);
                          const planDateOnly = new Date(planDate);
                          planDateOnly.setHours(0, 0, 0, 0);
                          
                          const diffDays = Math.round((planDateOnly.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
                          let dateLabel = planDate.toLocaleDateString("en-US", {
                            weekday: "long",
                            year: "numeric",
                            month: "long",
                            day: "numeric"
                          });
                          
                          // Add relative date indicator
                          let badgeClass = "bg-blue-500/20 text-blue-300 border border-blue-500/40 font-medium";
                          if (diffDays === 0) {
                            dateLabel = `📅 Today - ${dateLabel}`;
                            badgeClass = "bg-green-500/20 text-green-300 border border-green-500/40 font-medium";
                          } else if (diffDays === 1) {
                            dateLabel = `📅 Tomorrow - ${dateLabel}`;
                            badgeClass = "bg-yellow-500/20 text-yellow-300 border border-yellow-500/40 font-medium";
                          } else if (diffDays === -1) {
                            dateLabel = `📅 Yesterday - ${dateLabel}`;
                            badgeClass = "bg-gray-500/20 text-gray-300 border border-gray-500/40 font-medium";
                          } else if (diffDays > 1) {
                            dateLabel = `📅 In ${diffDays} days - ${dateLabel}`;
                          } else {
                            dateLabel = `📅 ${Math.abs(diffDays)} days ago - ${dateLabel}`;
                          }
                          
                          return (
                            <Badge key="plan-date" className={badgeClass}>
                              {dateLabel}
                            </Badge>
                          );
                        }
                      } catch (e) {
                        console.warn("Error formatting plan_start_date:", e);
                        return null;
                      }
                    })()}
                    <Badge variant="outline" className="font-medium">
                      {selectedList.item_count || 0} items
                    </Badge>
                    <Badge className="bg-green-500/20 text-green-300 border border-green-500/40 font-medium">
                      Purchased: {purchasedCount}
                    </Badge>
                    <Badge className="bg-orange-500/20 text-orange-300 border border-orange-500/40 font-medium">
                      Remaining: {remainingCount}
                    </Badge>
                  </div>
                )}
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* Error message */}
        {error && !loading && (
          <Card className="mb-6 border-destructive/20 bg-destructive/5">
            <CardContent className="pt-6">
              <p className="text-destructive">{error}</p>
            </CardContent>
          </Card>
        )}

        {/* Shopping items table */}
        {selectedListId ? (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.6 }}
          >
            <Card className="shadow-xl bg-background_alt border-secondary/20 backdrop-blur-sm">
              <CardHeader className="pb-4">
                <CardTitle className="text-2xl flex items-center gap-2">
                  <svg className="w-6 h-6 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                  Item List ({items.length})
                </CardTitle>
                <CardDescription className="text-sm mt-1">
                  {items.length === 0 
                    ? "This list is currently empty. Add items to get started."
                    : "Manage items in your shopping list"}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {items.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-16">
                    <motion.div
                      initial={{ scale: 0.9, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      transition={{ duration: 0.3 }}
                      className="text-center"
                    >
                      <div className="inline-flex items-center justify-center w-16 h-16 bg-secondary/10 rounded-full mb-4">
                        <svg className="w-8 h-8 text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z" />
                        </svg>
                      </div>
                      <p className="text-secondary mb-4 text-lg">No items in the list yet</p>
                      <Button onClick={handleAddItem} className="gap-2 bg-gradient-to-r from-accent to-accent/80 hover:from-accent/90 hover:to-accent/70 shadow-lg">
                        <IoAdd className="h-5 w-5" />
                        Add First Item
                      </Button>
                    </motion.div>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow className="hover:bg-transparent">
                          <TableHead className="w-12 font-semibold">Purchased</TableHead>
                          <TableHead className="font-semibold">Ingredient Name</TableHead>
                          <TableHead className="font-semibold">Quantity</TableHead>
                          <TableHead className="font-semibold">Unit</TableHead>
                          <TableHead className="font-semibold">Category</TableHead>
                          <TableHead className="text-right font-semibold">Actions</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {items.map((item, index) => (
                          <TableRow 
                            key={index}
                            className={`hover:bg-foreground/5 transition-colors ${item.purchased ? "opacity-60 line-through" : ""}`}
                          >
                            <TableCell>
                              <Button
                                size="icon"
                                variant="ghost"
                                onClick={() => handleTogglePurchased(item)}
                                className="h-8 w-8 hover:bg-green-500/10"
                              >
                                {item.purchased ? (
                                  <IoCheckmarkCircle className="w-5 h-5 text-green-500" />
                                ) : (
                                  <IoCheckmarkCircleOutline className="w-5 h-5 text-secondary" />
                                )}
                              </Button>
                            </TableCell>
                            <TableCell className="font-medium">{item.ingredient_name}</TableCell>
                            <TableCell>{item.quantity}</TableCell>
                            <TableCell>{item.unit}</TableCell>
                            <TableCell>
                              <Badge variant="outline" className="text-xs">
                                {item.category || "general"}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex justify-end gap-2">
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => handleEditItem(item)}
                                  className="h-8 w-8 hover:bg-accent/10"
                                >
                                  <IoCreate className="h-4 w-4" />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => handleDeleteItem(item)}
                                  className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                                >
                                  <IoTrash className="h-4 w-4" />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>
        ) : (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.6 }}
          >
            <Card className="shadow-xl bg-background_alt border-secondary/20 backdrop-blur-sm">
              <CardContent className="pt-6">
                <div className="flex flex-col items-center justify-center py-16">
                  <motion.div
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ duration: 0.3 }}
                    className="text-center"
                  >
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-secondary/10 rounded-full mb-4">
                      <svg className="w-8 h-8 text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z" />
                      </svg>
                    </div>
                    <p className="text-secondary mb-4 text-lg">
                      {lists.length === 0 
                        ? "You don't have any shopping lists yet. Create a meal plan to automatically generate a shopping list."
                        : "Please select a shopping list"}
                    </p>
                  </motion.div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
};

export default ShoppingListPage;

