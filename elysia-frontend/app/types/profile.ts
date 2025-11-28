export type UserProfile = {
  user_id: string;
  age: number;
  gender: "male" | "female" | "other";
  weight_kg: number;
  height_cm: number;
  activity_level: "sedentary" | "light" | "moderate" | "very_active" | "extra_active";
  goal?: "weight_loss" | "weight_gain" | "muscle_gain" | "gym" | "maintenance" | null;
  diet_type?: string | null;
  allergens?: string[];
  preferences?: string[];
  max_cooking_time_min?: number | null;
  available_equipment?: string[];
  tdee_kcal?: number;
  protein_g?: number;
  fat_g?: number;
  carb_g?: number;
  micronutrient_targets?: Record<string, number>;
  created_at?: string;
  updated_at?: string;
};


