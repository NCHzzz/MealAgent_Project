import { host } from "@/app/components/host";

export type UserProfileResponse = {
  user_id?: string;
  email?: string;
  display_name?: string;
  age?: number;
  gender?: string;
  weight_kg?: number;
  height_cm?: number;
  activity_level?: string;
  goal?: "weight_loss" | "weight_gain" | "muscle_gain" | "gym" | "maintenance" | null;
  diet_type?: string;
  allergens?: string[];
  preferences?: string[];
  max_cooking_time_min?: number;
  available_equipment?: string[];
  tdee_kcal?: number;
  protein_g?: number;
  fat_g?: number;
  carb_g?: number;
  created_at?: string;
  updated_at?: string;
};

export type AuthSuccessResponse = {
  error: string;
  user_id: string;
  email: string;
  display_name?: string;
  token: string;
  profile?: UserProfileResponse;
};

export type AuthErrorResponse = {
  error: string;
  user_id?: null;
  email?: null;
  token?: null;
};

export type RegisterPayload = {
  email: string;
  password: string;
  display_name: string;
  age?: number;
  gender?: string;
  weight_kg?: number;
  height_cm?: number;
  activity_level?: string;
  goal?: "weight_loss" | "weight_gain" | "muscle_gain" | "gym" | "maintenance";
  diet_type?: string;
  allergens?: string[];
  preferences?: string[];
  max_cooking_time_min?: number;
  available_equipment?: string[];
};

export type LoginPayload = {
  email: string;
  password: string;
};

export type ProfileUpdatePayload = {
  display_name?: string;
  age?: number;
  gender?: string;
  weight_kg?: number;
  height_cm?: number;
  activity_level?: string;
  goal?: "weight_loss" | "weight_gain" | "muscle_gain" | "gym" | "maintenance";
  timeline_months?: 3 | 6;  // Goal timeline: 3 (faster) or 6 (sustainable) months
  diet_type?: string;
  allergens?: string[];
  preferences?: string[];
  max_cooking_time_min?: number;
  available_equipment?: string[];
};

async function request<T>(
  path: string,
  options: RequestInit
): Promise<T | AuthErrorResponse> {
  try {
    const response = await fetch(`${host}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });

    const data = await response.json();
    if (!response.ok) {
      return {
        error: data?.detail || data?.error || "Request failed",
        user_id: null,
        email: null,
        token: null,
      };
    }
    return data as T;
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : "Request failed",
      user_id: null,
      email: null,
      token: null,
    };
  }
}

export async function registerUser(
  payload: RegisterPayload
): Promise<AuthSuccessResponse | AuthErrorResponse> {
  return request<AuthSuccessResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function loginUser(
  payload: LoginPayload
): Promise<AuthSuccessResponse | AuthErrorResponse> {
  return request<AuthSuccessResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function logoutUser(token: string): Promise<void> {
  if (!token) return;
  try {
    await fetch(`${host}/auth/logout`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
  } catch (_err) {
    // ignore
  }
}

export async function fetchProfile(
  token: string
): Promise<{ error: string; profile?: UserProfileResponse }> {
  const result = await request<{ error: string; profile: UserProfileResponse }>(
    "/auth/profile",
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );
  if ("user_id" in result) {
    return { error: result.error };
  }
  return result as { error: string; profile?: UserProfileResponse };
}

export async function updateProfile(
  token: string,
  payload: ProfileUpdatePayload
): Promise<{ error: string; profile?: UserProfileResponse }> {
  const result = await request<{ error: string; profile: UserProfileResponse }>(
    "/auth/profile",
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    }
  );
  if ("user_id" in result) {
    return { error: result.error };
  }
  return result as { error: string; profile?: UserProfileResponse };
}
