"use client";

import { ChangeEvent, useContext, useEffect, useMemo, useState } from "react";
import { UserProfile } from "@/app/types/profile";
import { saveUserProfile } from "@/app/api/profile";
import { ToastContext } from "@/app/components/contexts/ToastContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type ProfileFormProps = {
  userId: string;
  initialProfile?: UserProfile | null;
  onSaved?: (profile: UserProfile) => void;
  submitLabel?: string;
  compact?: boolean;
};

const activityLevels = [
  "sedentary",
  "light",
  "moderate",
  "very_active",
  "extra_active",
] as const;

const genders = ["male", "female", "other"] as const;

type FormState = {
  age: number | "";
  gender: UserProfile["gender"];
  weight_kg: number | "";
  height_cm: number | "";
  activity_level: UserProfile["activity_level"];
  goal: UserProfile["goal"];
  diet_type: string;
  allergens: string;
  preferences: string;
  max_cooking_time_min: number | "";
  available_equipment: string;
};

const defaultFormState: FormState = {
  age: "",
  gender: "other",
  weight_kg: "",
  height_cm: "",
  activity_level: "moderate",
  goal: null,
  diet_type: "",
  allergens: "",
  preferences: "",
  max_cooking_time_min: "",
  available_equipment: "",
};

export default function ProfileForm({
  userId,
  initialProfile,
  onSaved,
  submitLabel = "Save Profile",
  compact = false,
}: ProfileFormProps) {
  const { showErrorToast, showSuccessToast } = useContext(ToastContext);
  const [form, setForm] = useState<FormState>(defaultFormState);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!initialProfile) {
      setForm(defaultFormState);
      return;
    }
    setForm({
      age: initialProfile.age ?? "",
      gender: initialProfile.gender ?? "other",
      weight_kg: initialProfile.weight_kg ?? "",
      height_cm: initialProfile.height_cm ?? "",
      activity_level: initialProfile.activity_level ?? "moderate",
      goal: initialProfile.goal ?? null,
      diet_type: initialProfile.diet_type || "",
      allergens: (initialProfile.allergens || []).join(", "),
      preferences: (initialProfile.preferences || []).join(", "),
      max_cooking_time_min: initialProfile.max_cooking_time_min ?? "",
      available_equipment: (initialProfile.available_equipment || []).join(", "),
    });
  }, [initialProfile]);

  const disabled = useMemo(
    () =>
      !form.age ||
      !form.weight_kg ||
      !form.height_cm ||
      saving ||
      !userId.trim(),
    [form.age, form.weight_kg, form.height_cm, saving, userId]
  );

  const handleChange = (
    key: keyof FormState,
    value: string | number | ""
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const parseList = (value: string) =>
    value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!userId) {
      showErrorToast("Missing user id", "Please log in before saving profile.");
      return;
    }

    try {
      setSaving(true);
      const payload: Partial<UserProfile> = {
        user_id: userId,
        age: Number(form.age),
        gender: form.gender,
        weight_kg: Number(form.weight_kg),
        height_cm: Number(form.height_cm),
        activity_level: form.activity_level,
        goal: form.goal || null,
        diet_type: form.diet_type || null,
        allergens: parseList(form.allergens),
        preferences: parseList(form.preferences),
        max_cooking_time_min: form.max_cooking_time_min
          ? Number(form.max_cooking_time_min)
          : null,
        available_equipment: parseList(form.available_equipment),
      };

      const response = await saveUserProfile(userId, payload);
      if (response.error) {
        showErrorToast("Failed to save profile", response.error);
        return;
      }

      if (response.profile) {
        onSaved?.(response.profile);
      }
      showSuccessToast(
        "Profile saved",
        "Your nutritional profile has been updated."
      );
    } finally {
      setSaving(false);
    }
  };

  const fieldClass = compact ? "grid grid-cols-1 gap-2" : "grid gap-6";

  return (
    <form
      onSubmit={handleSubmit}
      className={`${fieldClass} w-full`}
      data-testid="profile-form"
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <Label>Age *</Label>
          <Input
            type="number"
            min={1}
            max={120}
            value={form.age}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              handleChange("age", event.target.value)
            }
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="profile-gender">Gender *</Label>
          <select
            id="profile-gender"
            className="border rounded-md bg-background p-2"
            value={form.gender}
            aria-label="Gender"
            onChange={(event: ChangeEvent<HTMLSelectElement>) =>
              handleChange(
                "gender",
                event.target.value as UserProfile["gender"]
              )
            }
          >
            {genders.map((gender) => (
              <option key={gender} value={gender}>
                {gender}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <Label>Weight (kg) *</Label>
          <Input
            type="number"
            min={1}
            max={500}
            value={form.weight_kg}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              handleChange("weight_kg", event.target.value)
            }
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label>Height (cm) *</Label>
          <Input
            type="number"
            min={1}
            max={300}
            value={form.height_cm}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              handleChange("height_cm", event.target.value)
            }
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="profile-activity">Activity Level *</Label>
        <select
          id="profile-activity"
          className="border rounded-md bg-background p-2"
          value={form.activity_level}
            aria-label="Activity level"
          onChange={(event: ChangeEvent<HTMLSelectElement>) =>
            handleChange(
              "activity_level",
              event.target.value as UserProfile["activity_level"]
            )
          }
        >
          {activityLevels.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="profile-goal">Goal</Label>
        <select
          id="profile-goal"
          className="border rounded-md bg-background p-2"
          value={form.goal || ""}
          aria-label="Goal"
          onChange={(event: ChangeEvent<HTMLSelectElement>) =>
            handleChange("goal", event.target.value)
          }
        >
          <option value="">Select your goal...</option>
          <option value="maintenance">Maintenance (Duy trì cân nặng)</option>
          <option value="weight_loss">Weight Loss (Giảm cân)</option>
          <option value="weight_gain">Weight Gain (Tăng cân)</option>
          <option value="muscle_gain">Muscle Gain (Tăng cơ)</option>
          <option value="gym">Gym (Tập gym)</option>
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="profile-diet-type">Diet Type</Label>
        <Input
          id="profile-diet-type"
          value={form.diet_type}
          onChange={(event: ChangeEvent<HTMLInputElement>) =>
            handleChange("diet_type", event.target.value)
          }
          placeholder="vegetarian, keto..."
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="profile-allergens">Allergens (comma separated)</Label>
        <textarea
          id="profile-allergens"
          className="border rounded-md bg-background p-2 min-h-[80px]"
          placeholder="e.g., peanuts, soy"
          aria-label="Allergens"
          value={form.allergens}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
            handleChange("allergens", event.target.value)
          }
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="profile-preferences">
          Preferences (comma separated)
        </Label>
        <textarea
          id="profile-preferences"
          className="border rounded-md bg-background p-2 min-h-[80px]"
          placeholder="e.g., spicy food, vietnamese"
          aria-label="Preferences"
          value={form.preferences}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
            handleChange("preferences", event.target.value)
          }
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="profile-max-time">Max Cooking Time (minutes)</Label>
          <Input
            id="profile-max-time"
            type="number"
            min={0}
            value={form.max_cooking_time_min}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              handleChange("max_cooking_time_min", event.target.value)
            }
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="profile-equipment">
            Available Equipment (comma separated)
          </Label>
          <textarea
            id="profile-equipment"
            className="border rounded-md bg-background p-2 min-h-[80px]"
             placeholder="e.g., oven, air fryer"
             aria-label="Available kitchen equipment"
            value={form.available_equipment}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
              handleChange("available_equipment", event.target.value)
            }
          />
        </div>
      </div>

      <Button type="submit" disabled={disabled}>
        {saving ? "Saving..." : submitLabel}
      </Button>
    </form>
  );
}


