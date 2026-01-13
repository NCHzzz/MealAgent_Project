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
import { 
  IoRefresh, 
  IoAdd, 
  IoTrash, 
  IoCreate, 
  IoCheckmarkCircle, 
  IoCheckmarkCircleOutline,
  IoFishOutline,
  IoLeafOutline,
  IoWaterOutline,
  IoNutritionOutline,
  IoFlaskOutline,
  IoEllipsisHorizontalCircleOutline,
  IoChevronDown,
  IoChevronUp,
  IoCartOutline
} from "react-icons/io5";
import { Badge } from "@/components/ui/badge";


/* Helper to guess category if missing or generic */
const assignCategory = (name: string, currentCategory?: string): string => {
  if (currentCategory && currentCategory !== "general" && currentCategory !== "Khác") {
    return currentCategory;
  }
  
  const lowerName = name.toLowerCase();
  
  // Keywords for categories
  const meatSeafood = ["thịt", "bò", "gà", "heo", "lợn", "cá", "tôm", "mực", "cua", "ngêu", "sò", "ốc", "hải sản", "xúc xích", "jambon", "chả", "giò"];
  const vegHerbs = ["rau", "củ", "quả", "hành", "tỏi", "ớt", "gừng", "nấm", "cà", "bí", "khoai", "măng", "cải", "xà lách", "ngò", "thì là", "chanh", "sả", "riềng", "nghệ", "lá", "đậu", "giá"];
  const fruits = ["táo", "cam", "quýt", "bưởi", "nho", "dưa", "xoài", "chuối", "lê", "mận", "đào", "ổi", "thơm", "dứa"];
  const dairy = ["sữa", "phô mai", "bơ", "kem", "trứng", "yaourt", "sữa chua"];
  const grains = ["gạo", "mì", "bún", "phở", "nui", "miến", "hủ tiếu", "bánh", "bột", "ngô", "bắp", "khoai tây", "khoai lang"];
  const spicesPantry = ["mắm", "muối", "đường", "tiêu", "hạt nêm", "bột ngọt", "dầu", "tương", "giấm", "ngũ vị hương", "cà ri", "sa tế", "sốt", "xốt", "mật ong", "đồ hộp"];
  const drinks = ["nước", "bia", "rượu", "trà", "cà phê", "sinh tố", "nước ép"];

  if (meatSeafood.some(k => lowerName.includes(k))) return "Thịt & Hải sản";
  if (vegHerbs.some(k => lowerName.includes(k))) return "Rau củ & Thảo mộc";
  if (fruits.some(k => lowerName.includes(k))) return "Trái cây";
  if (dairy.some(k => lowerName.includes(k))) return "Sữa & Phô mai";
  if (grains.some(k => lowerName.includes(k))) return "Ngũ cốc & Tinh bột";
  if (spicesPantry.some(k => lowerName.includes(k))) return "Gia vị & Đồ khô";
  if (drinks.some(k => lowerName.includes(k))) return "Đồ uống";
  
  return "general";
};

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

  /* Grouping Logic */
  const groupedItems = React.useMemo(() => {
    const active = items.filter(i => !i.purchased);
    const purchased = items.filter(i => i.purchased);

    const groups: Record<string, ShoppingItem[]> = {};
    
    active.forEach(item => {
      // Auto-assign category if missing or generic
      const cat = assignCategory(item.ingredient_name, item.category);
      if (!groups[cat]) {
        groups[cat] = [];
      }
      groups[cat].push(item);
    });

    return {
      activeGroups: groups,
      purchasedItems: purchased
    };
  }, [items]);

  const categoryOrder = [
    "Thịt & Hải sản",
    "Rau củ & Thảo mộc",
    "Trái cây",
    "Sữa & Phô mai",
    "Ngũ cốc & Tinh bột",
    "Gia vị & Đồ khô",
    "Đồ uống",
    "general"
  ];



  const getCategoryIcon = (category: string) => {
    switch (category) {
      case "Thịt & Hải sản": return <IoFishOutline className="w-6 h-6" />;
      case "Rau củ & Thảo mộc": return <IoLeafOutline className="w-6 h-6" />;
      case "Trái cây": return <IoNutritionOutline className="w-6 h-6" />;
      case "Sữa & Phô mai": return <IoWaterOutline className="w-6 h-6" />;
      case "Ngũ cốc & Tinh bột": return <IoNutritionOutline className="w-6 h-6" />;
      case "Gia vị & Đồ khô": return <IoFlaskOutline className="w-6 h-6" />;
      case "Đồ uống": return <IoWaterOutline className="w-6 h-6" />;
      default: return <IoEllipsisHorizontalCircleOutline className="w-6 h-6" />;
    }
  };

  const getCategoryLabel = (category: string) => {
    return category === "general" ? "Khác" : category;
  };

  const sortedCategories = Object.keys(groupedItems.activeGroups).sort((a, b) => {
    const indexA = categoryOrder.indexOf(a);
    const indexB = categoryOrder.indexOf(b);
    // If both are in the known list, sort by index
    if (indexA !== -1 && indexB !== -1) return indexA - indexB;
    // If only A is known, it comes first
    if (indexA !== -1) return -1;
    // If only B is known, it comes first
    if (indexB !== -1) return 1;
    // Otherwise sort alphabetically
    return a.localeCompare(b);
  });

  const [expandedPurchased, setExpandedPurchased] = useState(false);

  const fetchShoppingLists = async () => {
    if (!id) {
      setError("ID người dùng không tồn tại");
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
        setError("Không thể tải dữ liệu danh sách mua sắm");
      }
    } catch (err) {
      console.error("Error fetching shopping lists:", err);
      setError("Đã xảy ra lỗi khi tải danh sách mua sắm");
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
      setError("Vui lòng chọn danh sách mua sắm trước");
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
    if (!id || !selectedListId || !confirm(`Bạn có chắc chắn muốn xóa "${item.ingredient_name}"?`)) {
      return;
    }

    try {
      const result = await deleteShoppingItems(id, selectedListId, [item]);
      if (result) {
        await fetchShoppingLists();
      } else {
        setError("Không thể xóa mục");
      }
    } catch (err) {
      console.error("Error deleting item:", err);
      setError("Đã xảy ra lỗi khi xóa mục");
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
      setError("Đã xảy ra lỗi khi cập nhật trạng thái");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id || !selectedListId) return;

    if (!formData.ingredient_name.trim()) {
      setError("Tên nguyên liệu không được để trống");
      return;
    }

    if (formData.quantity <= 0) {
      setError("Số lượng phải lớn hơn 0");
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
        setError(editingItem ? "Không thể cập nhật mục" : "Không thể thêm mục");
      }
    } catch (err) {
      console.error("Error saving item:", err);
      setError("Đã xảy ra lỗi khi lưu mục");
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-secondary">
          Vui lòng đăng nhập để quản lý danh sách mua sắm.
        </p>
      </div>
    );
  }

  if (loading && lists.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-secondary">Đang tải danh sách mua sắm...</p>
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
            Danh sách mua sắm
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="text-secondary max-w-2xl mx-auto text-base md:text-lg"
          >
            Quản lý danh sách nguyên liệu cần mua cho các bữa ăn. Đánh dấu hoàn thành khi bạn đã mua xong.
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
                Thêm mục
              </Button>
            </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{editingItem ? "Sửa mục" : "Thêm mục mới"}</DialogTitle>
                  <DialogDescription>
                    {editingItem ? "Cập nhật thông tin mục trong danh sách" : "Thêm mục mới vào danh sách mua sắm"}
                  </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div>
                    <Label>Tên nguyên liệu *</Label>
                    <Input
                      value={formData.ingredient_name}
                      onChange={(e) => setFormData({ ...formData, ingredient_name: e.target.value })}
                      placeholder="Ví dụ: Gạo, Thịt gà, Rau củ..."
                      required
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label>Số lượng *</Label>
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
                      <Label>Đơn vị *</Label>
                      <Input
                        value={formData.unit}
                        onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
                        placeholder="g, kg, ml, l..."
                        required
                      />
                    </div>
                  </div>
                  <div>
                    <Label>Danh mục</Label>
                    <Select
                      value={formData.category}
                      onValueChange={(value) => setFormData({ ...formData, category: value })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn danh mục" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="general">Khác</SelectItem>
                        <SelectItem value="Thịt & Hải sản">Thịt & Hải sản</SelectItem>
                        <SelectItem value="Sữa & Phô mai">Sữa & Phô mai</SelectItem>
                        <SelectItem value="Rau củ & Thảo mộc">Rau củ & Thảo mộc</SelectItem>
                        <SelectItem value="Ngũ cốc & Tinh bột">Ngũ cốc & Tinh bột</SelectItem>
                        <SelectItem value="Gia vị & Đồ khô">Gia vị & Đồ khô</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {error && (
                    <p className="text-sm text-destructive">{error}</p>
                  )}
                  <div className="flex justify-end gap-2">
                    <Button type="button" variant="outline" onClick={() => setIsDialogOpen(false)}>
                      Hủy
                    </Button>
                    <Button type="submit">
                      {editingItem ? "Cập nhật" : "Thêm"}
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
                  <Label className="text-sm font-semibold">Chọn danh sách:</Label>
                <Select value={selectedListId || ""} onValueChange={handleListChange}>
                  <SelectTrigger className="w-[300px]">
                    <SelectValue placeholder="Chọn danh sách" />
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
                            // Format: "Kế hoạch: Thứ, DD/MM/YYYY"
                            const dayName = planDate.toLocaleDateString("vi-VN", { weekday: "long" });
                            const dateStr = planDate.toLocaleDateString("vi-VN");
                            dateLabel = ` - Kế hoạch: ${dayName}, ${dateStr}`;
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
                            dateLabel = ` - Tạo: ${createdDate.toLocaleDateString("vi-VN")}`;
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
                          let dateLabel = planDate.toLocaleDateString("vi-VN", {
                            weekday: "long",
                            year: "numeric",
                            month: "long",
                            day: "numeric"
                          });
                          
                          // Add relative date indicator
                          let badgeClass = "bg-blue-500/20 text-blue-300 border border-blue-500/40 font-medium";
                          if (diffDays === 0) {
                            dateLabel = `📅 Hôm nay - ${dateLabel}`;
                            badgeClass = "bg-green-500/20 text-green-300 border border-green-500/40 font-medium";
                          } else if (diffDays === 1) {
                            dateLabel = `📅 Ngày mai - ${dateLabel}`;
                            badgeClass = "bg-yellow-500/20 text-yellow-300 border border-yellow-500/40 font-medium";
                          } else if (diffDays === -1) {
                            dateLabel = `📅 Hôm qua - ${dateLabel}`;
                            badgeClass = "bg-gray-500/20 text-gray-300 border border-gray-500/40 font-medium";
                          } else if (diffDays > 1) {
                            dateLabel = `📅 Còn ${diffDays} ngày - ${dateLabel}`;
                          } else {
                            dateLabel = `📅 ${Math.abs(diffDays)} ngày trước - ${dateLabel}`;
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
                      {selectedList.item_count || 0} mục
                    </Badge>
                    <Badge className="bg-green-500/20 text-green-300 border border-green-500/40 font-medium">
                      Đã mua: {purchasedCount}
                    </Badge>
                    <Badge className="bg-orange-500/20 text-orange-300 border border-orange-500/40 font-medium">
                      Còn lại: {remainingCount}
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
            className="space-y-8"
          >
            {/* Active Items Grouped by Category */}
            {items.length === 0 ? (
              <Card className="shadow-xl bg-background_alt border-secondary/20 backdrop-blur-sm">
                 <CardContent className="flex flex-col items-center justify-center py-16">
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
                      <p className="text-secondary mb-4 text-lg">Chưa có mục nào trong danh sách</p>
                      <Button onClick={handleAddItem} className="gap-2 bg-gradient-to-r from-accent to-accent/80 hover:from-accent/90 hover:to-accent/70 shadow-lg">
                        <IoAdd className="h-5 w-5" />
                        Thêm mục đầu tiên
                      </Button>
                    </motion.div>
                 </CardContent>
              </Card>
            ) : (
              <>
                {/* Active Items Categories */}
                {sortedCategories.length > 0 ? (
                   sortedCategories.map(category => (
                    <div key={category} className="mb-8 last:mb-0">
                      <div className="flex items-center gap-4 mb-5 px-1 pt-2">
                          <div className="p-3 bg-gradient-to-br from-accent to-accent/80 rounded-xl text-white shadow-lg shadow-accent/20">
                            {getCategoryIcon(category)}
                          </div>
                          <h3 className="font-bold text-2xl text-white flex items-center gap-3 tracking-tight" style={{ textShadow: '0 2px 10px rgba(0,0,0,0.5)' }}>
                            {getCategoryLabel(category)}
                            <Badge className="bg-white/10 text-white hover:bg-white/20 ml-2 h-7 min-w-7 flex items-center justify-center rounded-full px-2.5 text-sm border-0">
                              {groupedItems.activeGroups[category].length}
                            </Badge>
                          </h3>
                      </div>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                        {groupedItems.activeGroups[category].map((item, idx) => (
                           <motion.div 
                              key={idx} 
                              layoutId={`item-${item.ingredient_name}-${idx}`}
                              className="group relative flex items-start p-3 bg-card/60 backdrop-blur-sm border border-white/10 rounded-xl shadow-sm hover:shadow-lg hover:border-accent/40 hover:bg-card/80 transition-all duration-200"
                           >
                              {/* Checkbox area */}
                              <div className="mr-3 mt-1">
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => handleTogglePurchased(item)}
                                  className="h-6 w-6 rounded-full border-2 border-secondary/40 text-transparent hover:border-green-500 hover:text-green-500 hover:bg-green-500/10 p-0 transition-colors"
                                >
                                  <IoCheckmarkCircle className="w-full h-full opacity-0 hover:opacity-100 transition-opacity" />
                                </Button>
                              </div>
                              
                              {/* Content area */}
                              <div className="flex-1 min-w-0 mr-2">
                                <div className="flex flex-col">
                                  <span className="font-bold text-lg text-white/90 line-clamp-2 leading-tight mb-1">
                                    {item.ingredient_name}
                                  </span>
                                  <span className="text-base font-semibold text-accent" style={{ textShadow: '0 0 10px rgba(234, 88, 12, 0.2)' }}>
                                    {item.quantity} <span className="text-white/60 font-medium">{item.unit}</span>
                                  </span>
                                </div>
                              </div>

                              {/* Actions - Always visible on mobile, visible on hover desktop, or just subtle */}
                              <div className="flex flex-col gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity absolute right-2 top-2 sm:static">
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => handleEditItem(item)}
                                  className="h-7 w-7 text-muted-foreground hover:text-accent hover:bg-accent/10 rounded-md"
                                >
                                  <IoCreate className="h-4 w-4" />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => handleDeleteItem(item)}
                                  className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-md"
                                >
                                  <IoTrash className="h-4 w-4" />
                                </Button>
                              </div>
                           </motion.div>
                        ))}
                      </div>
                    </div>
                   ))
                ) : (
                   /* If no active items but have purchased items, show a message */
                   groupedItems.purchasedItems.length > 0 && <div className="text-center text-secondary py-12 italic">Không có mục nào cần mua! 😍</div>
                )}

                {/* Purchased Items Section */}
                {groupedItems.purchasedItems.length > 0 && (
                  <div className="mt-12 pt-8 border-t border-border/20">
                    <div 
                      className="flex items-center justify-between cursor-pointer group mb-6"
                      onClick={() => setExpandedPurchased(!expandedPurchased)}
                    >
                      <div className="flex items-center gap-3">
                         <div className="p-2 bg-green-500/10 rounded-lg text-green-600">
                            <IoCartOutline className="w-5 h-5" />
                         </div>
                        <h3 className="font-bold text-xl text-secondary/80 group-hover:text-foreground transition-colors">Đã mua</h3>
                        <Badge variant="outline" className="text-secondary/70 border-secondary/30 ml-2">
                          {groupedItems.purchasedItems.length}
                        </Badge>
                      </div>
                      <Button variant="ghost" size="sm" className="h-9 w-9 p-0 text-secondary rounded-full bg-secondary/10 group-hover:bg-secondary/20 transition-colors">
                        {expandedPurchased ? <IoChevronUp /> : <IoChevronDown />}
                      </Button>
                    </div>
                    
                    {expandedPurchased && (
                       <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 opacity-70">
                        {groupedItems.purchasedItems.map((item, idx) => (
                           <motion.div 
                              key={idx} 
                              initial={{ opacity: 0 }} 
                              animate={{ opacity: 1 }}
                              className="flex items-center p-3 bg-muted/40 border border-transparent rounded-xl"
                           >
                              <div className="mr-3">
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  onClick={() => handleTogglePurchased(item)}
                                  className="h-6 w-6 rounded-full bg-green-500 text-white hover:bg-red-500 hover:text-white p-0 transition-colors"
                                >
                                  <IoCheckmarkCircle className="w-4 h-4" />
                                </Button>
                              </div>
                              
                              <div className="flex-1 min-w-0">
                                <p className="font-medium text-secondary line-through truncate">{item.ingredient_name}</p>
                                <p className="text-sm text-secondary/60 line-through">
                                  {item.quantity} {item.unit}
                                </p>
                              </div>

                              <Button
                                size="icon"
                                variant="ghost"
                                onClick={() => handleDeleteItem(item)}
                                className="h-8 w-8 text-secondary/40 hover:text-destructive hover:bg-destructive/10"
                              >
                                <IoTrash className="h-4 w-4" />
                              </Button>
                           </motion.div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
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
                        ? "Bạn chưa có danh sách mua sắm nào. Tạo kế hoạch bữa ăn để tự động tạo danh sách mua sắm."
                        : "Vui lòng chọn một danh sách mua sắm"}
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

