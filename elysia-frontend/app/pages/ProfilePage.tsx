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
      goal: profile?.goal ?? undefined,
      timeline_months: (profile as any)?.timeline_months || 3,
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
    (profile as any)?.timeline_months,
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
      transition={{ duration: 0.45 }}
      className="min-h-screen overflow-y-auto bg-gradient-to-br from-background via-background_alt to-background_alt/30"
    >
      <div className="container mx-auto px-4 py-10 max-w-6xl pb-20">
        {/* Hero header */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-8"
        >
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-r from-primary to-accent rounded-full mb-4 shadow-lg">
            <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
          <h1 className="text-3xl md:text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-accent mb-2">
            Personal Profile
          </h1>
          <p className="text-secondary max-w-2xl mx-auto">
            Provide your health metrics and preferences to generate tailored meal plans and accurate macro targets.
          </p>
        </motion.div>

        {/* Grid layout: form + side card */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          <div className="lg:col-span-2">
            {needsSetup && (
              <Card className="mb-6 border-warning/20 bg-warning/5 shadow-md">
                <CardHeader>
                  <CardTitle className="text-warning">Complete Your Profile</CardTitle>
                  <CardDescription className="text-warning/80">
                    Add these details so MealAgent can calculate macros correctly: {missingFields.join(", ")}
                  </CardDescription>
                </CardHeader>
              </Card>
            )}

            <Card className="shadow-lg bg-background_alt border border-secondary/10">
              <CardHeader>
                <CardTitle>Personal details</CardTitle>
                <CardDescription>These values power TDEE and goal-based adjustments.</CardDescription>
              </CardHeader>
              <CardContent>
                <form className="space-y-6" onSubmit={handleSubmit}>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <Label className="text-sm font-medium">Display name</Label>
                      <Input
                        value={form.display_name || ""}
                        onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                        className="h-11"
                        placeholder="Your name"
                      />
                    </div>
                    <div>
                      <Label className="text-sm font-medium">Diet type</Label>
                      <Input
                        value={form.diet_type || ""}
                        onChange={(e) => setForm({ ...form, diet_type: e.target.value })}
                        placeholder="balanced, keto, vegetarian..."
                        className="h-11"
                      />
                    </div>
                    <div>
                      <Label className="text-sm font-medium">Age</Label>
                      <Input type="number" min={1} value={form.age ?? ""} onChange={(e) => setForm({ ...form, age: Number(e.target.value) || undefined })} className="h-11" />
                    </div>
                    <div>
                      <Label className="text-sm font-medium">Gender</Label>
                      <Select value={form.gender || ""} onValueChange={(value) => setForm({ ...form, gender: value || undefined })}>
                        <SelectTrigger className="h-11">
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
                      <Label className="text-sm font-medium">Weight (kg)</Label>
                      <Input type="number" min={1} value={form.weight_kg ?? ""} onChange={(e) => setForm({ ...form, weight_kg: Number(e.target.value) || undefined })} className="h-11" />
                    </div>
                    <div>
                      <Label className="text-sm font-medium">Height (cm)</Label>
                      <Input type="number" min={30} value={form.height_cm ?? ""} onChange={(e) => setForm({ ...form, height_cm: Number(e.target.value) || undefined })} className="h-11" />
                    </div>
                    <div>
                      <Label className="text-sm font-medium">Activity level</Label>
                      <Select value={form.activity_level || ""} onValueChange={(value) => setForm({ ...form, activity_level: value as ProfileUpdatePayload["activity_level"] })}>
                        <SelectTrigger className="h-11">
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
                      <Label className="text-sm font-medium">Goal</Label>
                      <Select value={form.goal || ""} onValueChange={(value) => setForm({ ...form, goal: (value as ProfileUpdatePayload["goal"]) || undefined })}>
                        <SelectTrigger className="h-11">
                          <SelectValue placeholder="Select your goal..." />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="maintenance">Maintenance</SelectItem>
                          <SelectItem value="weight_loss">Weight Loss</SelectItem>
                          <SelectItem value="weight_gain">Weight Gain</SelectItem>
                          <SelectItem value="muscle_gain">Muscle Gain</SelectItem>
                          <SelectItem value="gym">Gym</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    {(form.goal === "weight_loss" || form.goal === "weight_gain") && (
                      <div>
                        <Label className="text-sm font-medium">Timeline</Label>
                        <Select value={String(form.timeline_months || 3)} onValueChange={(value) => setForm({ ...form, timeline_months: Number(value) as 3 | 6 })}>
                          <SelectTrigger className="h-11">
                            <SelectValue placeholder="Select timeline..." />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="3">3 months</SelectItem>
                            <SelectItem value="6">6 months</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    )}
                    <div>
                      <Label className="text-sm font-medium">Max cooking time (min)</Label>
                      <Input type="number" min={10} value={form.max_cooking_time_min ?? ""} onChange={(e) => setForm({ ...form, max_cooking_time_min: Number(e.target.value) || undefined })} className="h-11" />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                      <Label className="text-sm font-medium">Allergens</Label>
                      <Textarea value={allergensInput} onChange={(e) => setForm({ ...form, allergens: e.target.value ? e.target.value.split(",").map((i) => i.trim()) : [] })} className="min-h-[80px]" placeholder="nuts, dairy, gluten" />
                    </div>
                    <div>
                      <Label className="text-sm font-medium">Preferences</Label>
                      <Textarea value={preferencesInput} onChange={(e) => setForm({ ...form, preferences: e.target.value ? e.target.value.split(",").map((i) => i.trim()) : [] })} className="min-h-[80px]" placeholder="organic, spicy" />
                    </div>
                    <div>
                      <Label className="text-sm font-medium">Kitchen equipment</Label>
                      <Textarea value={equipmentInput} onChange={(e) => setForm({ ...form, available_equipment: e.target.value ? e.target.value.split(",").map((i) => i.trim()) : [] })} className="min-h-[80px]" placeholder="oven, microwave" />
                    </div>
                  </div>

                  <div className="flex justify-center gap-3 pt-2">
                    <Button type="submit" disabled={submitting} className="px-6 py-3 rounded-lg shadow-md">
                      {submitting ? "Saving..." : "Save profile"}
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          </div>

          {/* Side: Nutritional targets */}
          <aside className="w-full">
            {(profile?.tdee_kcal || profile?.protein_g || profile?.fat_g || profile?.carb_g) && (
              <Card className="sticky top-24 shadow-xl">
                <CardHeader>
                  <CardTitle>Your Targets</CardTitle>
                  <CardDescription>Auto-calculated from your profile</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-gradient-to-br from-orange-50 to-orange-100 p-3 rounded-lg text-center">
                      <p className="text-xs text-secondary">TDEE</p>
                      <p className="text-xl font-semibold text-orange-600">{profile?.tdee_kcal ? Math.round(profile.tdee_kcal) : '—'}</p>
                      <p className="text-xs text-secondary">kcal/day</p>
                    </div>
                    <div className="bg-gradient-to-br from-blue-50 to-blue-100 p-3 rounded-lg text-center">
                      <p className="text-xs text-secondary">Protein</p>
                      <p className="text-xl font-semibold text-blue-600">{profile?.protein_g ? profile.protein_g.toFixed(1) : '—'}</p>
                      <p className="text-xs text-secondary">g/day</p>
                    </div>
                    <div className="bg-gradient-to-br from-yellow-50 to-yellow-100 p-3 rounded-lg text-center">
                      <p className="text-xs text-secondary">Fat</p>
                      <p className="text-xl font-semibold text-yellow-600">{profile?.fat_g ? profile.fat_g.toFixed(1) : '—'}</p>
                      <p className="text-xs text-secondary">g/day</p>
                    </div>
                    <div className="bg-gradient-to-br from-green-50 to-green-100 p-3 rounded-lg text-center">
                      <p className="text-xs text-secondary">Carbs</p>
                      <p className="text-xl font-semibold text-green-600">{profile?.carb_g ? profile.carb_g.toFixed(1) : '—'}</p>
                      <p className="text-xs text-secondary">g/day</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </aside>
        </div>
      </div>
    </motion.div>
  );
};

export default ProfilePage;

