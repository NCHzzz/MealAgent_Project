import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";

interface DataEditorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (data: any) => Promise<void>;
  properties: { [key: string]: string };
  initialData?: any;
  collectionName: string;
}

const DataEditorModal: React.FC<DataEditorModalProps> = ({
  isOpen,
  onClose,
  onSave,
  properties,
  initialData,
  collectionName,
}) => {
  const [formData, setFormData] = useState<any>({});
  const [loading, setLoading] = useState(false);
  // Keep track of raw string input for object fields to allow invalid JSON while typing
  const [rawJsonInput, setRawJsonInput] = useState<{ [key: string]: string }>({});

  useEffect(() => {
    if (initialData) {
      setFormData({ ...initialData });
      // Initialize raw json inputs
      const newRawJson: { [key: string]: string } = {};
      Object.entries(properties).forEach(([key, type]) => {
        if ((type === "object" || type === "object[]") && initialData[key]) {
          newRawJson[key] = JSON.stringify(initialData[key], null, 2);
        }
      });
      setRawJsonInput(newRawJson);
    } else {
      setFormData({});
      setRawJsonInput({});
    }
  }, [initialData, isOpen, properties]);

  const handleChange = (key: string, value: any) => {
    setFormData((prev: any) => ({ ...prev, [key]: value }));
  };

  const handleJsonChange = (key: string, value: string) => {
    setRawJsonInput((prev) => ({ ...prev, [key]: value }));
    try {
      const parsed = JSON.parse(value);
      handleChange(key, parsed);
    } catch (e) {
      // Invalid JSON, don't update formData yet, or update as undefined/null?
      // We'll just leave formData as is or maybe null to indicate invalid?
      // Ideally we should show validation error.
    }
  };

  const handleSubmit = async () => {
    setLoading(true);
    // For object fields, ensure we send the parsed JSON if available, or the raw string if we want to fail on backend (or validation here)
    // We strictly assume formData has valid data.
    await onSave(formData);
    setLoading(false);
    onClose();
  };

  const renderInput = (key: string, type: string) => {
    if (key === "uuid" || key === "_additional") return null;

    const value = formData[key] ?? "";
    const displayValue = value === null || value === undefined ? "" : value;

    if (type === "boolean") {
      return (
        <div className="flex items-center space-x-2">
          <Checkbox
            id={key}
            checked={!!value}
            onCheckedChange={(checked) => handleChange(key, checked)}
          />
          <Label htmlFor={key}>{key}</Label>
        </div>
      );
    }

    if (type === "object" || type === "object[]") {
         return (
            <div className="grid gap-2">
                <Label htmlFor={key}>{key} (JSON)</Label>
                <Textarea
                    id={key}
                    value={rawJsonInput[key] || ""}
                    onChange={(e) => handleJsonChange(key, e.target.value)}
                    className="font-mono text-xs"
                    rows={5}
                />
            </div>
        );
    }

    if (type === "text" && (String(value).length > 50 || key.includes("description") || key.includes("content"))) {
      return (
        <div className="grid gap-2">
          <Label htmlFor={key}>{key}</Label>
          <Textarea
            id={key}
            value={value}
            onChange={(e) => handleChange(key, e.target.value)}
          />
        </div>
      );
    }

    return (
      <div className="grid gap-2">
        <Label htmlFor={key}>{key}</Label>
        <Input
          id={key}
          type={type === "number" ? "number" : "text"}
          value={value}
          onChange={(e) =>
            handleChange(key, type === "number" ? Number(e.target.value) : e.target.value)
          }
        />
      </div>
    );
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[425px] md:max-w-[600px] lg:max-w-[800px] bg-background">
        <DialogHeader>
          <DialogTitle>
            {initialData ? "Edit Object" : "Add Object"} - {collectionName}
          </DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-4 max-h-[60vh] overflow-y-auto px-1">
          {Object.entries(properties).map(([key, type]) => (
            <div key={key}>{renderInput(key, type)}</div>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={loading}>
            {loading ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default DataEditorModal;
