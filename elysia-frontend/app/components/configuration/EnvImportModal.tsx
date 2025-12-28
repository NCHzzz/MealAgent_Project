"use client";

import React from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface EnvImportModalProps {
  isOpen: boolean;
  envContent: string;
  onOpenChange: (open: boolean) => void;
  onEnvContentChange: (content: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

/**
 * Modal component for importing API keys from .env file format
 * Supports both KEY=value and KEY="value" formats with comment filtering
 */
export default function EnvImportModal({
  isOpen,
  envContent,
  onOpenChange,
  onEnvContentChange,
  onSubmit,
  onCancel,
}: EnvImportModalProps) {
  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Nhập khóa API từ .env</DialogTitle>
          <DialogDescription>
            Dán nội dung file .env của bạn bên dưới. Chúng tôi sẽ tự động phân tích
            và thêm khóa API của bạn. Hỗ trợ cả định dạng <code>KEY=value</code> và{" "}
            <code>KEY=&quot;value&quot;</code>.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="space-y-2">
            <label htmlFor="env-content" className="text-sm font-medium">
              Nội dung .env
            </label>
            <textarea
              id="env-content"
              value={envContent}
              onChange={(e) => onEnvContentChange(e.target.value)}
              placeholder={`OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY="your_key_here"
GOOGLE_API_KEY=your_key_here`}
              className="flex min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-y"
              rows={8}
            />
            <p className="text-xs text-muted-foreground">
              Các chú thích (dòng bắt đầu bằng #) sẽ bị bỏ qua
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={onCancel}>
            Hủy
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!envContent.trim()}
            className="bg-accent/10 text-accent hover:bg-accent/20"
          >
            Nhập khóa
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
