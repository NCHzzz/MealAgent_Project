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
import { SessionContext } from "../components/contexts/SessionContext";
import { AuthContext } from "../components/contexts/AuthContext";
import {
  getPantry,
  createPantryItems,
  updatePantryItems,
  deletePantryItems,
  PantryItem,
} from "../api/pantry";
import { IoRefresh, IoAdd, IoTrash, IoCreate } from "react-icons/io5";

const PantryPage: React.FC = () => {
  const { id } = useContext(SessionContext);
  const { isAuthenticated } = useContext(AuthContext);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<PantryItem[]>([]);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [isDialogOpen, setIsDialogOpen] = useState<boolean>(false);
  const [editingItem, setEditingItem] = useState<PantryItem | null>(null);
  const [formData, setFormData] = useState<PantryItem>({
    ingredient_name: "",
    quantity: 0,
    unit: "g",
    fdc_id: undefined,
    expiry_date: undefined,
  });

  const fetchPantry = async () => {
    if (!id) {
      setError("User ID không tồn tại");
      setLoading(false);
      return;
    }

    try {
      setError(null);
      const data = await getPantry(id);
      
      if (data) {
        if (data.items) {
          setItems(data.items);
        } else if (data.state?.items) {
          setItems(data.state.items);
        } else {
          setItems([]);
        }
      } else {
        setError("Không thể tải dữ liệu kho");
      }
    } catch (err) {
      console.error("Error fetching pantry:", err);
      setError("Đã xảy ra lỗi khi tải dữ liệu kho");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated && id) {
      fetchPantry();
    }
  }, [id, isAuthenticated]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchPantry();
  };

  const handleAddItem = () => {
    setEditingItem(null);
    setFormData({
      ingredient_name: "",
      quantity: 0,
      unit: "g",
      fdc_id: undefined,
      expiry_date: undefined,
    });
    setIsDialogOpen(true);
  };

  const handleEditItem = (item: PantryItem) => {
    setEditingItem(item);
    setFormData({ ...item });
    setIsDialogOpen(true);
  };

  const handleDeleteItem = async (item: PantryItem) => {
    if (!id || !confirm(`Bạn có chắc muốn xóa "${item.ingredient_name}"?`)) {
      return;
    }

    try {
      const result = await deletePantryItems(id, [item]);
      if (result) {
        await fetchPantry();
      } else {
        setError("Không thể xóa vật phẩm");
      }
    } catch (err) {
      console.error("Error deleting item:", err);
      setError("Đã xảy ra lỗi khi xóa vật phẩm");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;

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
      
      if (editingItem) {
        // Update existing item
        result = await updatePantryItems(id, [formData]);
      } else {
        // Create new item
        result = await createPantryItems(id, [formData]);
      }

      if (result) {
        setIsDialogOpen(false);
        await fetchPantry();
      } else {
        setError(editingItem ? "Không thể cập nhật vật phẩm" : "Không thể thêm vật phẩm");
      }
    } catch (err) {
      console.error("Error saving item:", err);
      setError("Đã xảy ra lỗi khi lưu vật phẩm");
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-secondary">
          Vui lòng đăng nhập để quản lý kho của bạn.
        </p>
      </div>
    );
  }

  if (loading && items.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-secondary">Đang tải dữ liệu kho...</p>
      </div>
    );
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
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
            </svg>
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary via-accent to-accent mb-3"
          >
            Quản lý kho
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="text-secondary max-w-2xl mx-auto text-base md:text-lg"
          >
            Thêm, sửa, xóa các vật phẩm trong kho của bạn để MealAgent có thể tạo kế hoạch bữa ăn phù hợp hơn.
          </motion.p>
        </motion.div>

        {/* Action buttons */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="flex items-center justify-center gap-2 mb-8"
        >
          <div className="flex items-center gap-2">
            <Button 
              size="icon" 
              variant="outline" 
              onClick={handleRefresh} 
              disabled={loading || refreshing}
              className="h-11 w-11"
            >
              <IoRefresh className={`h-5 w-5 ${refreshing ? "animate-spin" : ""}`} />
            </Button>
            <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
              <DialogTrigger asChild>
                <Button onClick={handleAddItem} className="gap-2 h-11 px-6 bg-gradient-to-r from-accent to-accent/80 hover:from-accent/90 hover:to-accent/70 shadow-lg text-white font-medium">
                  <IoAdd className="h-5 w-5" />
                  Thêm vật phẩm
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{editingItem ? "Sửa vật phẩm" : "Thêm vật phẩm mới"}</DialogTitle>
                  <DialogDescription>
                    {editingItem ? "Cập nhật thông tin vật phẩm trong kho" : "Thêm vật phẩm mới vào kho của bạn"}
                  </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div>
                    <Label>Tên nguyên liệu *</Label>
                    <Input
                      value={formData.ingredient_name}
                      onChange={(e) => setFormData({ ...formData, ingredient_name: e.target.value })}
                      placeholder="Ví dụ: Gạo, Thịt gà, Rau cải..."
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
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label>FDC ID (tùy chọn)</Label>
                      <Input
                        type="number"
                        value={formData.fdc_id || ""}
                        onChange={(e) => setFormData({ ...formData, fdc_id: e.target.value ? parseInt(e.target.value) : undefined })}
                        placeholder="Food Data Central ID"
                      />
                    </div>
                    <div>
                      <Label>Hạn sử dụng (tùy chọn)</Label>
                      <Input
                        type="date"
                        value={formData.expiry_date ? formData.expiry_date.split("T")[0] : ""}
                        onChange={(e) => setFormData({ ...formData, expiry_date: e.target.value ? new Date(e.target.value).toISOString() : undefined })}
                      />
                    </div>
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
          </div>
        </motion.div>

        {/* Error message */}
        {error && !loading && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <Card className="mb-6 border-destructive/30 bg-destructive/10 shadow-lg backdrop-blur-sm">
              <CardContent className="pt-6">
                <p className="text-destructive flex items-center gap-2">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {error}
                </p>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {/* Pantry items table */}
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
                Danh sách vật phẩm ({items.length})
              </CardTitle>
              <CardDescription className="text-sm mt-1">
                {items.length === 0 
                  ? "Kho của bạn hiện đang trống. Hãy thêm vật phẩm để bắt đầu."
                  : "Quản lý các vật phẩm trong kho của bạn"}
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
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                    </svg>
                  </div>
                  <p className="text-secondary mb-4 text-lg">Chưa có vật phẩm nào trong kho</p>
                  <Button onClick={handleAddItem} className="gap-2 bg-gradient-to-r from-accent to-accent/80 hover:from-accent/90 hover:to-accent/70 shadow-lg">
                    <IoAdd className="h-5 w-5" />
                    Thêm vật phẩm đầu tiên
                  </Button>
                </motion.div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="font-semibold">Tên nguyên liệu</TableHead>
                      <TableHead className="font-semibold">Số lượng</TableHead>
                      <TableHead className="font-semibold">Đơn vị</TableHead>
                      <TableHead className="font-semibold">FDC ID</TableHead>
                      <TableHead className="font-semibold">Hạn sử dụng</TableHead>
                      <TableHead className="text-right font-semibold">Thao tác</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((item, index) => (
                        <TableRow 
                          key={index}
                          className="hover:bg-foreground/5 transition-colors"
                        >
                          <TableCell className="font-medium">{item.ingredient_name}</TableCell>
                          <TableCell>{item.quantity}</TableCell>
                          <TableCell>{item.unit}</TableCell>
                          <TableCell className="text-secondary">{item.fdc_id || "—"}</TableCell>
                          <TableCell>
                            {item.expiry_date 
                              ? new Date(item.expiry_date).toLocaleDateString("vi-VN")
                              : "—"}
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
      </div>
    </motion.div>
  );
};

export default PantryPage;

