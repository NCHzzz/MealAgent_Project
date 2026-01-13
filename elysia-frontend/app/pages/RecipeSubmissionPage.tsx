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
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
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
    submitRecipe,
    getMySubmissions,
    RecipeSubmission,
    RecipeSubmitData,
} from "../api/recipeSubmission";
import { IoRefresh, IoAdd, IoRestaurant, IoTime, IoPeople } from "react-icons/io5";
import { FaUtensils } from "react-icons/fa";

const RecipeSubmissionPage: React.FC = () => {
    const { id } = useContext(SessionContext);
    const { isAuthenticated } = useContext(AuthContext);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const [submissions, setSubmissions] = useState<RecipeSubmission[]>([]);
    const [refreshing, setRefreshing] = useState<boolean>(false);
    const [isDialogOpen, setIsDialogOpen] = useState<boolean>(false);
    const [submitting, setSubmitting] = useState<boolean>(false);
    const [statusFilter, setStatusFilter] = useState<string>("all");

    const [formData, setFormData] = useState<RecipeSubmitData>({
        dish_name: "",
        dish_type: "",
        serving_size: 2,
        cooking_time: 30,
        ingredients_with_qty: [],
        ingredients: [],
        cooking_method_array: [],
        image_link: "",
    });

    // Temp fields for array inputs
    const [ingredientsText, setIngredientsText] = useState<string>("");
    const [stepsText, setStepsText] = useState<string>("");

    const fetchSubmissions = async () => {
        if (!id) {
            setError("User ID không tồn tại");
            setLoading(false);
            return;
        }

        try {
            setError(null);
            const status = statusFilter === "all" ? undefined : statusFilter;
            const data = await getMySubmissions(id, status);

            if (data && data.submissions) {
                setSubmissions(data.submissions);
            } else if (data?.error) {
                setError(data.error);
            } else {
                setSubmissions([]);
            }
        } catch (err) {
            console.error("Error fetching submissions:", err);
            setError("Đã xảy ra lỗi khi tải dữ liệu");
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    };

    useEffect(() => {
        if (isAuthenticated && id) {
            fetchSubmissions();
        }
    }, [id, isAuthenticated, statusFilter]);

    const handleRefresh = () => {
        setRefreshing(true);
        fetchSubmissions();
    };

    const resetForm = () => {
        setFormData({
            dish_name: "",
            dish_type: "",
            serving_size: 2,
            cooking_time: 30,
            ingredients_with_qty: [],
            ingredients: [],
            cooking_method_array: [],
            image_link: "",
        });
        setIngredientsText("");
        setStepsText("");
    };

    const handleOpenDialog = () => {
        resetForm();
        setError(null);
        setSuccess(null);
        setIsDialogOpen(true);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!id) return;

        if (!formData.dish_name.trim()) {
            setError("Tên món ăn không được để trống");
            return;
        }

        setSubmitting(true);
        setError(null);
        setSuccess(null);

        try {
            // Parse ingredients and steps
            const ingredientsList = ingredientsText
                .split("\n")
                .map((s) => s.trim())
                .filter((s) => s.length > 0);

            const stepsList = stepsText
                .split("\n")
                .map((s) => s.trim())
                .filter((s) => s.length > 0);

            const submitData: RecipeSubmitData = {
                ...formData,
                ingredients_with_qty: ingredientsList,
                ingredients: ingredientsList.map((i) => i.replace(/^\d+\s*\w*\s*/i, "").trim()),
                cooking_method_array: stepsList,
            };

            const result = await submitRecipe(id, submitData);

            if (result?.error) {
                setError(result.error);
            } else if (result?.submission_id) {
                setSuccess(`Công thức "${formData.dish_name}" đã được gửi và đang chờ duyệt!`);
                setIsDialogOpen(false);
                fetchSubmissions();
            }
        } catch (err) {
            console.error("Error submitting recipe:", err);
            setError("Đã xảy ra lỗi khi gửi công thức");
        } finally {
            setSubmitting(false);
        }
    };

    const getStatusBadge = (status: string) => {
        switch (status) {
            case "pending":
                return <Badge variant="outline" className="bg-yellow-500/10 text-yellow-600 border-yellow-500/30">Chờ duyệt</Badge>;
            case "approved":
                return <Badge variant="outline" className="bg-green-500/10 text-green-600 border-green-500/30">Đã duyệt</Badge>;
            case "rejected":
                return <Badge variant="outline" className="bg-red-500/10 text-red-600 border-red-500/30">Từ chối</Badge>;
            default:
                return <Badge variant="outline">{status}</Badge>;
        }
    };

    if (!isAuthenticated) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <p className="text-secondary">
                    Vui lòng đăng nhập để gửi công thức nấu ăn.
                </p>
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
                        className="inline-flex items-center justify-center w-20 h-20 bg-gradient-to-r from-orange-500 via-red-500 to-pink-500 rounded-full mb-6 shadow-xl"
                    >
                        <FaUtensils className="w-10 h-10 text-white" />
                    </motion.div>
                    <motion.h1
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.5, delay: 0.2 }}
                        className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-orange-500 via-red-500 to-pink-500 mb-3"
                    >
                        Đóng góp công thức
                    </motion.h1>
                    <motion.p
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.5, delay: 0.3 }}
                        className="text-secondary max-w-2xl mx-auto text-base md:text-lg"
                    >
                        Chia sẻ công thức nấu ăn của bạn với cộng đồng. Sau khi được Admin duyệt, công thức sẽ được thêm vào hệ thống.
                    </motion.p>
                </motion.div>

                {/* Success message */}
                {success && (
                    <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.3 }}
                    >
                        <Card className="mb-6 border-green-500/30 bg-green-500/10 shadow-lg backdrop-blur-sm">
                            <CardContent className="pt-6">
                                <p className="text-green-600 flex items-center gap-2">
                                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                    </svg>
                                    {success}
                                </p>
                            </CardContent>
                        </Card>
                    </motion.div>
                )}

                {/* Action buttons */}
                <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.4 }}
                    className="flex flex-wrap items-center justify-center gap-3 mb-8"
                >
                    <Button
                        size="icon"
                        variant="outline"
                        onClick={handleRefresh}
                        disabled={loading || refreshing}
                        className="h-11 w-11"
                    >
                        <IoRefresh className={`h-5 w-5 ${refreshing ? "animate-spin" : ""}`} />
                    </Button>

                    <Select value={statusFilter} onValueChange={setStatusFilter}>
                        <SelectTrigger className="w-[160px] h-11">
                            <SelectValue placeholder="Lọc theo trạng thái" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">Tất cả</SelectItem>
                            <SelectItem value="pending">Chờ duyệt</SelectItem>
                            <SelectItem value="approved">Đã duyệt</SelectItem>
                            <SelectItem value="rejected">Từ chối</SelectItem>
                        </SelectContent>
                    </Select>

                    <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
                        <DialogTrigger asChild>
                            <Button
                                onClick={handleOpenDialog}
                                className="gap-2 h-11 px-6 bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-600 hover:to-red-600 shadow-lg text-white font-medium"
                            >
                                <IoAdd className="h-5 w-5" />
                                Gửi công thức mới
                            </Button>
                        </DialogTrigger>
                        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                            <DialogHeader>
                                <DialogTitle className="flex items-center gap-2 text-xl">
                                    <IoRestaurant className="text-orange-500" />
                                    Gửi công thức mới
                                </DialogTitle>
                                <DialogDescription>
                                    Điền thông tin công thức nấu ăn của bạn. Sau khi gửi, Admin sẽ xem xét và duyệt.
                                </DialogDescription>
                            </DialogHeader>
                            <form onSubmit={handleSubmit} className="space-y-4 mt-4">
                                {/* Dish name */}
                                <div>
                                    <Label className="font-medium">Tên món ăn *</Label>
                                    <Input
                                        value={formData.dish_name}
                                        onChange={(e) => setFormData({ ...formData, dish_name: e.target.value })}
                                        placeholder="Ví dụ: Phở bò, Bún chả, Cơm tấm..."
                                        className="mt-1"
                                        required
                                    />
                                </div>

                                {/* Dish type, serving, time */}
                                <div className="grid grid-cols-3 gap-4">
                                    <div>
                                        <Label className="font-medium flex items-center gap-1">
                                            <IoRestaurant className="text-sm" /> Loại món
                                        </Label>
                                        <Select
                                            value={formData.dish_type || ""}
                                            onValueChange={(v) => setFormData({ ...formData, dish_type: v })}
                                        >
                                            <SelectTrigger className="mt-1">
                                                <SelectValue placeholder="Chọn loại" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="Non-vegetarian">Có thịt</SelectItem>
                                                <SelectItem value="Vegetarian">Chay</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    <div>
                                        <Label className="font-medium flex items-center gap-1">
                                            <IoPeople className="text-sm" /> Khẩu phần
                                        </Label>
                                        <Input
                                            type="number"
                                            min={1}
                                            value={formData.serving_size || 2}
                                            onChange={(e) => setFormData({ ...formData, serving_size: parseInt(e.target.value) || 2 })}
                                            className="mt-1"
                                        />
                                    </div>
                                    <div>
                                        <Label className="font-medium flex items-center gap-1">
                                            <IoTime className="text-sm" /> Thời gian (phút)
                                        </Label>
                                        <Input
                                            type="number"
                                            min={0}
                                            value={formData.cooking_time || 30}
                                            onChange={(e) => setFormData({ ...formData, cooking_time: parseInt(e.target.value) || 30 })}
                                            className="mt-1"
                                        />
                                    </div>
                                </div>

                                {/* Ingredients */}
                                <div>
                                    <Label className="font-medium">Nguyên liệu (mỗi dòng 1 nguyên liệu)</Label>
                                    <Textarea
                                        value={ingredientsText}
                                        onChange={(e) => setIngredientsText(e.target.value)}
                                        placeholder="200g thịt bò&#10;1 củ hành tây&#10;2 thìa nước mắm&#10;..."
                                        className="mt-1 min-h-[120px]"
                                    />
                                </div>

                                {/* Cooking steps */}
                                <div>
                                    <Label className="font-medium">Các bước thực hiện (mỗi dòng 1 bước)</Label>
                                    <Textarea
                                        value={stepsText}
                                        onChange={(e) => setStepsText(e.target.value)}
                                        placeholder="Bước 1: Sơ chế nguyên liệu&#10;Bước 2: Ướp thịt với gia vị&#10;Bước 3: Xào thịt với hành&#10;..."
                                        className="mt-1 min-h-[150px]"
                                    />
                                </div>

                                {/* Image link */}
                                <div>
                                    <Label className="font-medium">Link hình ảnh (tùy chọn)</Label>
                                    <Input
                                        value={formData.image_link || ""}
                                        onChange={(e) => setFormData({ ...formData, image_link: e.target.value })}
                                        placeholder="https://example.com/image.jpg"
                                        className="mt-1"
                                    />
                                </div>

                                {/* Error */}
                                {error && (
                                    <p className="text-sm text-destructive">{error}</p>
                                )}

                                {/* Actions */}
                                <div className="flex justify-end gap-2 pt-4">
                                    <Button
                                        type="button"
                                        variant="outline"
                                        onClick={() => setIsDialogOpen(false)}
                                    >
                                        Hủy
                                    </Button>
                                    <Button
                                        type="submit"
                                        disabled={submitting}
                                        className="bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-600 hover:to-red-600"
                                    >
                                        {submitting ? "Đang gửi..." : "Gửi công thức"}
                                    </Button>
                                </div>
                            </form>
                        </DialogContent>
                    </Dialog>
                </motion.div>

                {/* Error message */}
                {error && !isDialogOpen && (
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

                {/* Submissions table */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.5 }}
                >
                    <Card className="shadow-xl bg-background_alt border-secondary/20 backdrop-blur-sm">
                        <CardHeader className="pb-4">
                            <CardTitle className="text-2xl flex items-center gap-2">
                                <FaUtensils className="text-orange-500" />
                                Công thức đã gửi ({submissions.length})
                            </CardTitle>
                            <CardDescription className="text-sm mt-1">
                                {submissions.length === 0
                                    ? "Bạn chưa gửi công thức nào. Hãy chia sẻ món ăn yêu thích của bạn!"
                                    : "Theo dõi trạng thái các công thức bạn đã gửi"}
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            {loading && submissions.length === 0 ? (
                                <div className="flex items-center justify-center py-16">
                                    <p className="text-secondary">Đang tải...</p>
                                </div>
                            ) : submissions.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-16">
                                    <motion.div
                                        initial={{ scale: 0.9, opacity: 0 }}
                                        animate={{ scale: 1, opacity: 1 }}
                                        transition={{ duration: 0.3 }}
                                        className="text-center"
                                    >
                                        <div className="inline-flex items-center justify-center w-16 h-16 bg-orange-500/10 rounded-full mb-4">
                                            <FaUtensils className="w-8 h-8 text-orange-500" />
                                        </div>
                                        <p className="text-secondary mb-4 text-lg">Chưa có công thức nào</p>
                                        <Button
                                            onClick={handleOpenDialog}
                                            className="gap-2 bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-600 hover:to-red-600 shadow-lg"
                                        >
                                            <IoAdd className="h-5 w-5" />
                                            Gửi công thức đầu tiên
                                        </Button>
                                    </motion.div>
                                </div>
                            ) : (
                                <div className="overflow-x-auto">
                                    <Table>
                                        <TableHeader>
                                            <TableRow className="hover:bg-transparent">
                                                <TableHead className="font-semibold">Tên món</TableHead>
                                                <TableHead className="font-semibold">Loại</TableHead>
                                                <TableHead className="font-semibold">Ngày gửi</TableHead>
                                                <TableHead className="font-semibold">Trạng thái</TableHead>
                                                <TableHead className="font-semibold">Ghi chú</TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {submissions.map((sub) => (
                                                <TableRow
                                                    key={sub.submission_id}
                                                    className="hover:bg-foreground/5 transition-colors"
                                                >
                                                    <TableCell className="font-medium">{sub.dish_name}</TableCell>
                                                    <TableCell className="capitalize">{sub.dish_type || "—"}</TableCell>
                                                    <TableCell>
                                                        {sub.submitted_at
                                                            ? new Date(sub.submitted_at).toLocaleDateString("vi-VN")
                                                            : "—"}
                                                    </TableCell>
                                                    <TableCell>{getStatusBadge(sub.status)}</TableCell>
                                                    <TableCell className="max-w-[200px] truncate">
                                                        {sub.status === "rejected" && sub.rejection_reason
                                                            ? sub.rejection_reason
                                                            : "—"}
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

export default RecipeSubmissionPage;
