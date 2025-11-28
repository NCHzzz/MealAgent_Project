"use client";

import React, { useContext, useEffect, useMemo, useState } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AuthContext } from "../components/contexts/AuthContext";
import { ProfileUpdatePayload } from "../api/auth/signup";

const REQUIRED_FIELDS: Array<
  keyof Pick<
    ProfileUpdatePayload,
    "age" | "weight_kg" | "height_cm" | "activity_level" | "diet_type"
  >
> = ["age", "weight_kg", "height_cm", "activity_level", "diet_type"];

const ProfilePage: React.FC = () => {
  const { profile, saveProfile, logout, isAuthenticated, loading, authUser } =
    useContext(AuthContext);
  const [form, setForm] = useState<ProfileUpdatePayload>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setForm({
      display_name: profile?.display_name || authUser?.display_name || "",
      age: profile?.age,
      gender: profile?.gender,
      weight_kg: profile?.weight_kg,
      height_cm: profile?.height_cm,
      activity_level: profile?.activity_level,
      goal: profile?.goal,
      diet_type: profile?.diet_type,
      allergens: profile?.allergens || [],
      preferences: profile?.preferences || [],
      max_cooking_time_min: profile?.max_cooking_time_min,
      available_equipment: profile?.available_equipment || [],
    });
  }, [
    profile?.display_name,
    profile?.age,
    profile?.gender,
    profile?.weight_kg,
    profile?.height_cm,
    profile?.activity_level,
    profile?.goal,
    profile?.diet_type,
    profile?.allergens,
    profile?.preferences,
    profile?.max_cooking_time_min,
    profile?.available_equipment,
    authUser?.display_name,
  ]);

  const allergensInput = useMemo(
    () => (form.allergens?.length ? form.allergens.join(", ") : ""),
    [form.allergens]
  );

  const preferencesInput = useMemo(
    () => (form.preferences?.length ? form.preferences.join(", ") : ""),
    [form.preferences]
  );

  const equipmentInput = useMemo(
    () =>
      form.available_equipment?.length
        ? form.available_equipment.join(", ")
        : "",
    [form.available_equipment]
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    const payload: ProfileUpdatePayload = {
      ...form,
      allergens: form.allergens?.filter(Boolean),
      preferences: form.preferences?.filter(Boolean),
      available_equipment: form.available_equipment?.filter(Boolean),
    };
    await saveProfile(payload);
    setSubmitting(false);
  };

  const missingFields = REQUIRED_FIELDS.filter(
    (field) => !profile || profile[field] === undefined || profile[field] === ""
  );
  const needsSetup = missingFields.length > 0;

  if (!isAuthenticated) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-secondary">
          Please login or register to configure your MealAgent profile.
        </p>
      </div>
    );
  }

  if (loading && !profile) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-secondary">Loading profile...</p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex flex-1 flex-col gap-6 w-full max-w-4xl mx-auto py-6"
    >
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold text-primary">
          MealAgent profile & nutrition targets
        </h1>
        <p className="text-secondary">
          Cập nhật cân nặng, chiều cao, mức vận động để MealAgent tính toán
          thực đơn Việt Nam chính xác cho bạn.
        </p>
      </div>

      {needsSetup && (
        <Card className="border-warning/30 bg-warning/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-warning text-base">
              Missing health metrics
            </CardTitle>
            <CardDescription className="text-warning/80">
              Provide the following fields so macros and Vietnamese meal plans
              stay accurate: {missingFields.join(", ")}.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      <Card className="border-secondary/10 bg-background_alt w-full">
        <CardHeader>
          <CardTitle>Personal details</CardTitle>
          <CardDescription>
            These values power Mifflin-St Jeor TDEE calculation + goal-based macro adjustments for every plan.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label>Display name</Label>
                <Input
                  value={form.display_name || ""}
                  onChange={(e) =>
                    setForm({ ...form, display_name: e.target.value })
                  }
                />
              </div>
              <div>
                <Label>Diet type</Label>
                <Input
                  value={form.diet_type || ""}
                  onChange={(e) =>
                    setForm({ ...form, diet_type: e.target.value })
                  }
                  placeholder="balanced, keto, vegetarian..."
                />
              </div>
              <div>
                <Label>Age</Label>
                <Input
                  type="number"
                  min={1}
                  value={form.age ?? ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      age: Number(e.target.value) || undefined,
                    })
                  }
                />
              </div>
              <div>
                <Label>Gender</Label>
                <Select
                  value={form.gender || ""}
                  onValueChange={(value) =>
                    setForm({ ...form, gender: value || undefined })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="male">Male</SelectItem>
                    <SelectItem value="female">Female</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Weight (kg)</Label>
                <Input
                  type="number"
                  min={1}
                  value={form.weight_kg ?? ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      weight_kg: Number(e.target.value) || undefined,
                    })
                  }
                />
              </div>
              <div>
                <Label>Height (cm)</Label>
                <Input
                  type="number"
                  min={30}
                  value={form.height_cm ?? ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      height_cm: Number(e.target.value) || undefined,
                    })
                  }
                />
              </div>
              <div>
                <Label>Activity level</Label>
                <Select
                  value={form.activity_level || ""}
                  onValueChange={(value) =>
                    setForm({
                      ...form,
                      activity_level:
                        value as ProfileUpdatePayload["activity_level"],
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="sedentary">Sedentary</SelectItem>
                    <SelectItem value="light">Light</SelectItem>
                    <SelectItem value="moderate">Moderate</SelectItem>
                    <SelectItem value="very_active">Very active</SelectItem>
                    <SelectItem value="extra_active">Extra active</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Goal</Label>
                <Select
                  value={form.goal || ""}
                  onValueChange={(value) =>
                    setForm({
                      ...form,
                      goal: value as ProfileUpdatePayload["goal"] || undefined,
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select your goal..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="maintenance">Maintenance (Duy trì cân nặng)</SelectItem>
                    <SelectItem value="weight_loss">Weight Loss (Giảm cân)</SelectItem>
                    <SelectItem value="weight_gain">Weight Gain (Tăng cân)</SelectItem>
                    <SelectItem value="muscle_gain">Muscle Gain (Tăng cơ)</SelectItem>
                    <SelectItem value="gym">Gym (Tập gym)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Max cooking time (minutes)</Label>
                <Input
                  type="number"
                  min={10}
                  value={form.max_cooking_time_min ?? ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      max_cooking_time_min:
                        Number(e.target.value) || undefined,
                    })
                  }
                />
              </div>
            </div>
            <div>
              <Label>Allergens (comma separated)</Label>
              <Textarea
                value={allergensInput}
                onChange={(e) =>
                  setForm({
                    ...form,
                    allergens: e.target.value
                      ? e.target.value.split(",").map((item) => item.trim())
                      : [],
                  })
                }
              />
            </div>
            <div>
              <Label>Preferences (comma separated)</Label>
              <Textarea
                value={preferencesInput}
                onChange={(e) =>
                  setForm({
                    ...form,
                    preferences: e.target.value
                      ? e.target.value.split(",").map((item) => item.trim())
                      : [],
                  })
                }
              />
            </div>
            <div>
              <Label>Available kitchen equipment</Label>
              <Textarea
                value={equipmentInput}
                onChange={(e) =>
                  setForm({
                    ...form,
                    available_equipment: e.target.value
                      ? e.target.value.split(",").map((item) => item.trim())
                      : [],
                  })
                }
              />
            </div>
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <Button type="submit" disabled={submitting}>
                {submitting ? "Saving..." : "Save profile"}
              </Button>
              <Button type="button" variant="ghost" onClick={logout}>
                Logout
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Display calculated nutritional targets */}
      {(profile?.tdee_kcal || profile?.protein_g || profile?.fat_g || profile?.carb_g) && (
        <Card className="border-primary/20 bg-background_alt w-full">
          <CardHeader>
            <CardTitle>Your Nutritional Targets</CardTitle>
            <CardDescription>
              Calculated based on your profile and goal (automatically updated when you save).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="flex flex-col gap-1">
                <Label className="text-secondary text-sm">TDEE</Label>
                <p className="text-lg font-semibold">
                  {profile.tdee_kcal ? `${Math.round(profile.tdee_kcal)} kcal` : "—"}
                </p>
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-secondary text-sm">Protein</Label>
                <p className="text-lg font-semibold">
                  {profile.protein_g ? `${profile.protein_g.toFixed(1)}g` : "—"}
                </p>
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-secondary text-sm">Fat</Label>
                <p className="text-lg font-semibold">
                  {profile.fat_g ? `${profile.fat_g.toFixed(1)}g` : "—"}
                </p>
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-secondary text-sm">Carbs</Label>
                <p className="text-lg font-semibold">
                  {profile.carb_g ? `${profile.carb_g.toFixed(1)}g` : "—"}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </motion.div>
  );
};

export default ProfilePage;

