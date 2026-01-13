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
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
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
} from "@/components/ui/dialog";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
    getAllSubmissions,
    getPendingSubmissions,
    approveSubmission,
    rejectSubmission,
    RecipeSubmission,
} from "../api/recipeSubmission";
import { IoRefresh, IoCheckmark, IoClose, IoEye } from "react-icons/io5";
import { FaUserShield, FaUtensils } from "react-icons/fa";

const AdminRecipeReviewPage: React.FC = () => {
    const { id } = useContext(SessionContext);
    const { isAuthenticated, isAdmin } = useContext(AuthContext);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const [submissions, setSubmissions] = useState<RecipeSubmission[]>([]);
    const [refreshing, setRefreshing] = useState<boolean>(false);
    const [statusFilter, setStatusFilter] = useState<string>("pending");

    // Detail dialog
    const [selectedSubmission, setSelectedSubmission] = useState<RecipeSubmission | null>(null);
    const [isDetailOpen, setIsDetailOpen] = useState<boolean>(false);

    // Reject dialog
    const [isRejectOpen, setIsRejectOpen] = useState<boolean>(false);
    const [rejectReason, setRejectReason] = useState<string>("");
    const [processing, setProcessing] = useState<boolean>(false);

    // Approve confirm dialog
    const [isApproveOpen, setIsApproveOpen] = useState<boolean>(false);
    const [approveTarget, setApproveTarget] = useState<RecipeSubmission | null>(null);

    const fetchSubmissions = async () => {
        if (!id) {
            setError("User ID không tồn tại");
            setLoading(false);
            return;
        }

        try {
            setError(null);
            let data;

            if (statusFilter === "pending") {
                data = await getPendingSubmissions(id);
                if (data && data.pending) {
                    setSubmissions(data.pending);
                }
            } else {
                const status = statusFilter === "all" ? undefined : statusFilter;
                data = await getAllSubmissions(id, status);
                if (data && data.submissions) {
                    setSubmissions(data.submissions);
                }
            }

            if (data?.error) {
                setError(data.error);
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
        if (isAuthenticated && id && isAdmin) {
            fetchSubmissions();
        }
    }, [id, isAuthenticated, isAdmin, statusFilter]);

    const handleRefresh = () => {
        setRefreshing(true);
        fetchSubmissions();
    };

    const handleViewDetail = (submission: RecipeSubmission) => {
        setSelectedSubmission(submission);
        setIsDetailOpen(true);
    };

    const handleOpenApprove = (submission: RecipeSubmission) => {
        setApproveTarget(submission);
        setIsApproveOpen(true);
    };

    const handleConfirmApprove = async () => {
        if (!id || !approveTarget) return;

        setIsApproveOpen(false);
        setProcessing(true);
        setError(null);
        setSuccess(null);

        try {
            const result = await approveSubmission(id, approveTarget.submission_id);

            if (result?.error) {
                setError(result.error);
            } else {
                setSuccess(`Đã duyệt công thức "${approveTarget.dish_name}". Food ID: ${result?.food_id}`);
                setIsDetailOpen(false);
                fetchSubmissions();
            }
        } catch (err) {
            console.error("Error approving:", err);
            setError("Đã xảy ra lỗi khi duyệt");
        } finally {
            setProcessing(false);
            setApproveTarget(null);
        }
    };

    const handleOpenReject = (submission: RecipeSubmission) => {
        setSelectedSubmission(submission);
        setRejectReason("");
        setIsRejectOpen(true);
    };

    const handleReject = async () => {
        if (!id || !selectedSubmission || !rejectReason.trim()) {
            setError("Vui lòng nhập lý do từ chối");
            return;
        }

        setProcessing(true);
        setError(null);
        setSuccess(null);

        try {
            const result = await rejectSubmission(id, selectedSubmission.submission_id, rejectReason);

            if (result?.error) {
                setError(result.error);
            } else {
                setSuccess(`Đã từ chối công thức "${selectedSubmission.dish_name}"`);
                setIsRejectOpen(false);
                setIsDetailOpen(false);
                fetchSubmissions();
            }
        } catch (err) {
            console.error("Error rejecting:", err);
            setError("Đã xảy ra lỗi khi từ chối");
        } finally {
            setProcessing(false);
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

    // Access denied for non-admin
    if (!isAuthenticated || !isAdmin) {
        return (
            <div className="w-full h-full flex items-center justify-center">
                <Card className="max-w-md">
                    <CardContent className="pt-6 text-center">
                        <FaUserShield className="w-12 h-12 mx-auto text-secondary mb-4" />
                        <p className="text-secondary text-lg">
                            Bạn không có quyền truy cập trang này.
                        </p>
                        <p className="text-sm text-secondary/70 mt-2">
                            Chỉ Admin mới có thể xem và duyệt công thức.
                        </p>
                    </CardContent>
                </Card>
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
            <div className="w-full max-w-7xl mx-auto px-4 py-10 pb-20">
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
                        className="inline-flex items-center justify-center w-20 h-20 bg-gradient-to-r from-purple-600 via-blue-600 to-cyan-500 rounded-full mb-6 shadow-xl"
                    >
                        <FaUserShield className="w-10 h-10 text-white" />
                    </motion.div>
                    <motion.h1
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.5, delay: 0.2 }}
                        className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-600 via-blue-600 to-cyan-500 mb-3"
                    >
                        Quản lý công thức
                    </motion.h1>
                    <motion.p
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.5, delay: 0.3 }}
                        className="text-secondary max-w-2xl mx-auto text-base md:text-lg"
                    >
                        Xem xét và duyệt các công thức nấu ăn do người dùng gửi lên.
                    </motion.p>
                </motion.div>

                {/* Messages */}
                {success && (
                    <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                    >
                        <Card className="mb-6 border-green-500/30 bg-green-500/10">
                            <CardContent className="pt-6">
                                <p className="text-green-600 flex items-center gap-2">
                                    <IoCheckmark className="w-5 h-5" />
                                    {success}
                                </p>
                            </CardContent>
                        </Card>
                    </motion.div>
                )}

                {error && (
                    <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                    >
                        <Card className="mb-6 border-destructive/30 bg-destructive/10">
                            <CardContent className="pt-6">
                                <p className="text-destructive flex items-center gap-2">
                                    <IoClose className="w-5 h-5" />
                                    {error}
                                </p>
                            </CardContent>
                        </Card>
                    </motion.div>
                )}

                {/* Action bar */}
                <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.4 }}
                    className="flex flex-wrap items-center justify-between gap-3 mb-8"
                >
                    <div className="flex items-center gap-3">
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
                            <SelectTrigger className="w-[180px] h-11">
                                <SelectValue placeholder="Lọc theo trạng thái" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="pending">Chờ duyệt</SelectItem>
                                <SelectItem value="approved">Đã duyệt</SelectItem>
                                <SelectItem value="rejected">Từ chối</SelectItem>
                                <SelectItem value="all">Tất cả</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="flex items-center gap-2 text-sm text-secondary">
                        <span className="font-medium">{submissions.length}</span> công thức
                    </div>
                </motion.div>

                {/* Submissions table */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.5 }}
                >
                    <Card className="shadow-xl bg-background_alt border-secondary/20">
                        <CardHeader className="pb-4">
                            <CardTitle className="text-2xl flex items-center gap-2">
                                <FaUtensils className="text-purple-500" />
                                Danh sách công thức
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            {loading ? (
                                <div className="flex items-center justify-center py-16">
                                    <p className="text-secondary">Đang tải...</p>
                                </div>
                            ) : submissions.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-16">
                                    <div className="inline-flex items-center justify-center w-16 h-16 bg-secondary/10 rounded-full mb-4">
                                        <FaUtensils className="w-8 h-8 text-secondary" />
                                    </div>
                                    <p className="text-secondary text-lg">
                                        {statusFilter === "pending"
                                            ? "Không có công thức nào đang chờ duyệt"
                                            : "Không có công thức nào"}
                                    </p>
                                </div>
                            ) : (
                                <div className="overflow-x-auto">
                                    <Table>
                                        <TableHeader>
                                            <TableRow className="hover:bg-transparent">
                                                <TableHead className="font-semibold">Tên món</TableHead>
                                                <TableHead className="font-semibold">Người gửi</TableHead>
                                                <TableHead className="font-semibold">Loại</TableHead>
                                                <TableHead className="font-semibold">Ngày gửi</TableHead>
                                                <TableHead className="font-semibold">Trạng thái</TableHead>
                                                <TableHead className="text-right font-semibold">Thao tác</TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {submissions.map((sub) => (
                                                <TableRow
                                                    key={sub.submission_id}
                                                    className="hover:bg-foreground/5 transition-colors"
                                                >
                                                    <TableCell className="font-medium">{sub.dish_name}</TableCell>
                                                    <TableCell className="text-sm text-secondary">{sub.submitted_by}</TableCell>
                                                    <TableCell className="capitalize">{sub.dish_type || "—"}</TableCell>
                                                    <TableCell>
                                                        {sub.submitted_at
                                                            ? new Date(sub.submitted_at).toLocaleDateString("vi-VN")
                                                            : "—"}
                                                    </TableCell>
                                                    <TableCell>{getStatusBadge(sub.status)}</TableCell>
                                                    <TableCell className="text-right">
                                                        <div className="flex justify-end gap-2">
                                                            <Button
                                                                size="sm"
                                                                variant="ghost"
                                                                onClick={() => handleViewDetail(sub)}
                                                                className="h-8 px-3"
                                                            >
                                                                <IoEye className="h-4 w-4 mr-1" />
                                                                Xem
                                                            </Button>
                                                            {sub.status === "pending" && (
                                                                <>
                                                                    <Button
                                                                        size="sm"
                                                                        variant="ghost"
                                                                        onClick={() => handleOpenApprove(sub)}
                                                                        className="h-8 px-3 text-green-600 hover:text-green-700 hover:bg-green-500/10"
                                                                        disabled={processing}
                                                                    >
                                                                        <IoCheckmark className="h-4 w-4 mr-1" />
                                                                        Duyệt
                                                                    </Button>
                                                                    <Button
                                                                        size="sm"
                                                                        variant="ghost"
                                                                        onClick={() => handleOpenReject(sub)}
                                                                        className="h-8 px-3 text-red-600 hover:text-red-700 hover:bg-red-500/10"
                                                                        disabled={processing}
                                                                    >
                                                                        <IoClose className="h-4 w-4 mr-1" />
                                                                        Từ chối
                                                                    </Button>
                                                                </>
                                                            )}
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

                {/* Detail Dialog */}
                <Dialog open={isDetailOpen} onOpenChange={setIsDetailOpen}>
                    <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                        <DialogHeader>
                            <DialogTitle className="flex items-center gap-2 text-xl">
                                <FaUtensils className="text-purple-500" />
                                Chi tiết công thức
                            </DialogTitle>
                            <DialogDescription>
                                Xem chi tiết và quyết định duyệt hoặc từ chối
                            </DialogDescription>
                        </DialogHeader>

                        {selectedSubmission && (
                            <div className="space-y-4 mt-4">
                                {/* Basic info */}
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <Label className="text-secondary text-sm">Tên món</Label>
                                        <p className="font-medium text-lg">{selectedSubmission.dish_name}</p>
                                    </div>
                                    <div>
                                        <Label className="text-secondary text-sm">Trạng thái</Label>
                                        <div className="mt-1">{getStatusBadge(selectedSubmission.status)}</div>
                                    </div>
                                </div>

                                <div className="grid grid-cols-3 gap-4">
                                    <div>
                                        <Label className="text-secondary text-sm">Loại món</Label>
                                        <p className="capitalize">{selectedSubmission.dish_type || "—"}</p>
                                    </div>
                                    <div>
                                        <Label className="text-secondary text-sm">Khẩu phần</Label>
                                        <p>{selectedSubmission.serving_size || "—"} người</p>
                                    </div>
                                    <div>
                                        <Label className="text-secondary text-sm">Thời gian</Label>
                                        <p>{selectedSubmission.cooking_time || "—"} phút</p>
                                    </div>
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <Label className="text-secondary text-sm">Người gửi</Label>
                                        <p>{selectedSubmission.submitted_by}</p>
                                    </div>
                                    <div>
                                        <Label className="text-secondary text-sm">Ngày gửi</Label>
                                        <p>
                                            {selectedSubmission.submitted_at
                                                ? new Date(selectedSubmission.submitted_at).toLocaleString("vi-VN")
                                                : "—"}
                                        </p>
                                    </div>
                                </div>

                                {/* Ingredients */}
                                <div className="space-y-4">
                                    <div>
                                        <Label className="text-secondary text-sm font-medium">Nguyên liệu</Label>
                                        <div className="mt-2 p-3 bg-secondary/5 rounded-lg">
                                            {selectedSubmission.ingredients_with_qty?.length ? (
                                                <ul className="list-disc list-inside space-y-1">
                                                    {selectedSubmission.ingredients_with_qty.map((ing, i) => (
                                                        <li key={i}>{ing}</li>
                                                    ))}
                                                </ul>
                                            ) : (
                                                <p className="text-secondary">Không có thông tin</p>
                                            )}
                                        </div>
                                    </div>

                                    <div>
                                        <Label className="text-secondary text-sm font-medium">Các bước thực hiện</Label>
                                        <div className="mt-2 p-3 bg-secondary/5 rounded-lg">
                                            {selectedSubmission.cooking_method_array?.length ? (
                                                <ol className="list-decimal list-inside space-y-2">
                                                    {selectedSubmission.cooking_method_array.map((step, i) => (
                                                        <li key={i}>{step}</li>
                                                    ))}
                                                </ol>
                                            ) : (
                                                <p className="text-secondary">Không có thông tin</p>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* Image */}
                                {selectedSubmission.image_link && (
                                    <div>
                                        <Label className="text-secondary text-sm">Hình ảnh</Label>
                                        <img
                                            src={selectedSubmission.image_link}
                                            alt={selectedSubmission.dish_name}
                                            className="mt-2 max-h-48 rounded-lg object-cover"
                                            onError={(e) => {
                                                (e.target as HTMLImageElement).style.display = "none";
                                            }}
                                        />
                                    </div>
                                )}

                                {/* Rejection reason if rejected */}
                                {selectedSubmission.status === "rejected" && selectedSubmission.rejection_reason && (
                                    <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg">
                                        <Label className="text-red-600 text-sm">Lý do từ chối</Label>
                                        <p className="mt-1">{selectedSubmission.rejection_reason}</p>
                                    </div>
                                )}

                                {/* Actions for pending */}
                                {selectedSubmission.status === "pending" && (
                                    <div className="flex justify-end gap-2 pt-4 border-t">
                                        <Button
                                            variant="outline"
                                            onClick={() => setIsDetailOpen(false)}
                                        >
                                            Đóng
                                        </Button>
                                        <Button
                                            variant="outline"
                                            onClick={() => handleOpenReject(selectedSubmission)}
                                            className="text-red-600 border-red-500/30 hover:bg-red-500/10"
                                            disabled={processing}
                                        >
                                            <IoClose className="h-4 w-4 mr-1" />
                                            Từ chối
                                        </Button>
                                        <Button
                                            onClick={() => handleOpenApprove(selectedSubmission)}
                                            className="bg-green-600 hover:bg-green-700"
                                            disabled={processing}
                                        >
                                            <IoCheckmark className="h-4 w-4 mr-1" />
                                            Duyệt công thức
                                        </Button>
                                    </div>
                                )}
                            </div>
                        )}
                    </DialogContent>
                </Dialog>

                {/* Reject Dialog */}
                <Dialog open={isRejectOpen} onOpenChange={setIsRejectOpen}>
                    <DialogContent>
                        <DialogHeader>
                            <DialogTitle className="text-red-600">Từ chối công thức</DialogTitle>
                            <DialogDescription>
                                Nhập lý do từ chối để người dùng biết cần cải thiện điều gì.
                            </DialogDescription>
                        </DialogHeader>
                        <div className="space-y-4 mt-4">
                            <div>
                                <Label>Lý do từ chối *</Label>
                                <Textarea
                                    value={rejectReason}
                                    onChange={(e) => setRejectReason(e.target.value)}
                                    placeholder="Ví dụ: Thiếu thông tin nguyên liệu, hình ảnh không phù hợp..."
                                    className="mt-1 min-h-[100px]"
                                />
                            </div>
                            <div className="flex justify-end gap-2">
                                <Button variant="outline" onClick={() => setIsRejectOpen(false)}>
                                    Hủy
                                </Button>
                                <Button
                                    onClick={handleReject}
                                    className="bg-red-600 hover:bg-red-700"
                                    disabled={processing || !rejectReason.trim()}
                                >
                                    {processing ? "Đang xử lý..." : "Từ chối"}
                                </Button>
                            </div>
                        </div>
                    </DialogContent>
                </Dialog>

                {/* Approve Confirm AlertDialog */}
                <AlertDialog open={isApproveOpen} onOpenChange={setIsApproveOpen}>
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle className="text-green-600 flex items-center gap-2">
                                <IoCheckmark className="h-5 w-5" />
                                Xác nhận duyệt công thức
                            </AlertDialogTitle>
                            <AlertDialogDescription>
                                Bạn có chắc chắn muốn duyệt công thức <span className="font-semibold text-foreground">"{approveTarget?.dish_name}"</span>?
                                <br />
                                <span className="text-sm text-muted-foreground mt-2 block">
                                    Công thức sẽ được thêm vào hệ thống và hiển thị cho người dùng.
                                </span>
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogCancel onClick={() => setIsApproveOpen(false)}>
                                Hủy
                            </AlertDialogCancel>
                            <AlertDialogAction
                                onClick={handleConfirmApprove}
                                className="bg-green-600 hover:bg-green-700 text-white"
                            >
                                <IoCheckmark className="h-4 w-4 mr-1" />
                                Duyệt
                            </AlertDialogAction>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
            </div>
        </motion.div>
    );
};

export default AdminRecipeReviewPage;
