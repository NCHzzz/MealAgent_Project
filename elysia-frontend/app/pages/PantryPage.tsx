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
      className="min-h-screen overflow-y-auto bg-gradient-to-br from-background via-background_alt to-background_alt/30"
    >
      <div className="container mx-auto px-4 py-10 max-w-6xl pb-20">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="flex items-center justify-between mb-8"
        >
          <div>
            <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-r from-primary to-accent rounded-full mb-4 shadow-lg">
              <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
              </svg>
            </div>
            <h1 className="text-3xl md:text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-accent mb-2">
              Quản lý kho
            </h1>
            <p className="text-secondary max-w-2xl">
              Thêm, sửa, xóa các vật phẩm trong kho của bạn để MealAgent có thể tạo kế hoạch bữa ăn phù hợp hơn.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="icon" variant="outline" onClick={handleRefresh} disabled={loading || refreshing}>
              <IoRefresh className={refreshing ? "animate-spin" : ""} />
            </Button>
            <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
              <DialogTrigger asChild>
                <Button onClick={handleAddItem} className="gap-2">
                  <IoAdd />
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
          <Card className="mb-6 border-destructive/20 bg-destructive/5">
            <CardContent className="pt-6">
              <p className="text-destructive">{error}</p>
            </CardContent>
          </Card>
        )}

        {/* Pantry items table */}
        <Card className="shadow-lg bg-background_alt border-secondary/10">
          <CardHeader>
            <CardTitle>Danh sách vật phẩm ({items.length})</CardTitle>
            <CardDescription>
              {items.length === 0 
                ? "Kho của bạn hiện đang trống. Hãy thêm vật phẩm để bắt đầu."
                : "Quản lý các vật phẩm trong kho của bạn"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {items.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12">
                <p className="text-secondary mb-4">Chưa có vật phẩm nào trong kho</p>
                <Button onClick={handleAddItem} className="gap-2">
                  <IoAdd />
                  Thêm vật phẩm đầu tiên
                </Button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tên nguyên liệu</TableHead>
                      <TableHead>Số lượng</TableHead>
                      <TableHead>Đơn vị</TableHead>
                      <TableHead>FDC ID</TableHead>
                      <TableHead>Hạn sử dụng</TableHead>
                      <TableHead className="text-right">Thao tác</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((item, index) => (
                      <TableRow key={index}>
                        <TableCell className="font-medium">{item.ingredient_name}</TableCell>
                        <TableCell>{item.quantity}</TableCell>
                        <TableCell>{item.unit}</TableCell>
                        <TableCell>{item.fdc_id || "—"}</TableCell>
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
                            >
                              <IoCreate />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              onClick={() => handleDeleteItem(item)}
                              className="text-destructive hover:text-destructive"
                            >
                              <IoTrash />
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
      </div>
    </motion.div>
  );
};

export default PantryPage;

