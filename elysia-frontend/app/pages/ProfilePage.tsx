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
      className="w-full h-full overflow-y-auto bg-gradient-to-br from-background via-background_alt to-background_alt/30"
    >
      <div className="w-full max-w-6xl mx-auto px-4 py-10 pb-20">
        {/* Hero header */}
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
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary via-accent to-accent mb-3"
          >
            Personal Profile
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="text-secondary max-w-2xl mx-auto text-base md:text-lg"
          >
            Provide your health metrics and preferences to generate tailored meal plans and accurate macro targets.
          </motion.p>
        </motion.div>

        {/* Grid layout: form + side card */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          <div className="lg:col-span-2">
            {needsSetup && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.4 }}
              >
                <Card className="mb-6 border-warning/30 bg-warning/10 shadow-lg backdrop-blur-sm">
                  <CardHeader>
                    <CardTitle className="text-warning flex items-center gap-2">
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                      Complete Your Profile
                    </CardTitle>
                    <CardDescription className="text-warning/90">
                      Add these details so MealAgent can calculate macros correctly: {missingFields.join(", ")}
                    </CardDescription>
                  </CardHeader>
                </Card>
              </motion.div>
            )}

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.2 }}
            >
              <Card className="shadow-xl bg-background_alt border border-secondary/20 backdrop-blur-sm">
              <CardHeader className="pb-4">
                <CardTitle className="text-2xl flex items-center gap-2">
                  <svg className="w-6 h-6 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  Personal Details
                </CardTitle>
                <CardDescription className="text-sm mt-1">These values power TDEE and goal-based adjustments.</CardDescription>
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

                  <div className="flex justify-center gap-3 pt-4 border-t border-secondary/10">
                    <Button 
                      type="submit" 
                      disabled={submitting} 
                      className="px-8 py-3 rounded-lg shadow-lg bg-gradient-to-r from-accent to-accent/80 hover:from-accent/90 hover:to-accent/70 transition-all duration-300 font-semibold text-white"
                    >
                      {submitting ? (
                        <span className="flex items-center gap-2">
                          <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                          </svg>
                          Saving...
                        </span>
                      ) : (
                        <span className="flex items-center gap-2">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                          Save Profile
                        </span>
                      )}
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
            </motion.div>
          </div>

          {/* Side: Nutritional targets */}
          <aside className="w-full">
            {(profile?.tdee_kcal || profile?.protein_g || profile?.fat_g || profile?.carb_g) && (
              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.5, delay: 0.3 }}
              >
                <Card className="sticky top-24 shadow-2xl bg-background_alt border border-secondary/20 backdrop-blur-sm">
                  <CardHeader className="pb-4">
                    <CardTitle className="text-xl flex items-center gap-2">
                      <svg className="w-5 h-5 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                      </svg>
                      Your Targets
                    </CardTitle>
                    <CardDescription className="text-xs">Auto-calculated from your profile</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 gap-3">
                      <motion.div
                        whileHover={{ scale: 1.05 }}
                        className="bg-gradient-to-br from-orange-500/20 to-orange-600/30 p-4 rounded-xl text-center border border-orange-500/20 backdrop-blur-sm"
                      >
                        <p className="text-xs text-secondary mb-1 font-medium">TDEE</p>
                        <p className="text-2xl font-bold text-orange-400">{profile?.tdee_kcal ? Math.round(profile.tdee_kcal) : '—'}</p>
                        <p className="text-xs text-secondary mt-1">kcal/day</p>
                      </motion.div>
                      <motion.div
                        whileHover={{ scale: 1.05 }}
                        className="bg-gradient-to-br from-blue-500/20 to-blue-600/30 p-4 rounded-xl text-center border border-blue-500/20 backdrop-blur-sm"
                      >
                        <p className="text-xs text-secondary mb-1 font-medium">Protein</p>
                        <p className="text-2xl font-bold text-blue-400">{profile?.protein_g ? profile.protein_g.toFixed(1) : '—'}</p>
                        <p className="text-xs text-secondary mt-1">g/day</p>
                      </motion.div>
                      <motion.div
                        whileHover={{ scale: 1.05 }}
                        className="bg-gradient-to-br from-yellow-500/20 to-yellow-600/30 p-4 rounded-xl text-center border border-yellow-500/20 backdrop-blur-sm"
                      >
                        <p className="text-xs text-secondary mb-1 font-medium">Fat</p>
                        <p className="text-2xl font-bold text-yellow-400">{profile?.fat_g ? profile.fat_g.toFixed(1) : '—'}</p>
                        <p className="text-xs text-secondary mt-1">g/day</p>
                      </motion.div>
                      <motion.div
                        whileHover={{ scale: 1.05 }}
                        className="bg-gradient-to-br from-green-500/20 to-green-600/30 p-4 rounded-xl text-center border border-green-500/20 backdrop-blur-sm"
                      >
                        <p className="text-xs text-secondary mb-1 font-medium">Carbs</p>
                        <p className="text-2xl font-bold text-green-400">{profile?.carb_g ? profile.carb_g.toFixed(1) : '—'}</p>
                        <p className="text-xs text-secondary mt-1">g/day</p>
                      </motion.div>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}
          </aside>
        </div>
      </div>
    </motion.div>
  );
};

export default ProfilePage;

