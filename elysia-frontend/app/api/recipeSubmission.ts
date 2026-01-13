import { host } from "@/app/components/host";

// Types
export interface MacrosPerServing {
  kcal?: number;
  protein_g?: number;
  fat_g?: number;
  carb_g?: number;
}

export interface RecipeSubmission {
  uuid?: string;
  submission_id: string;
  submitted_by: string;
  submitted_at: string;
  status: "pending" | "approved" | "rejected";
  reviewed_by?: string;
  reviewed_at?: string;
  rejection_reason?: string;
  dish_name: string;
  dish_type?: string;
  serving_size?: number;
  cooking_time?: number;
  ingredients_with_qty?: string[];
  ingredients?: string[];
  cooking_method_array?: string[];
  image_link?: string;
  diet_type?: string[];
  allergens?: string[];
  devices?: string[];
  macros_per_serving?: MacrosPerServing;
}

export interface RecipeSubmitData {
  dish_name: string;
  dish_type?: string;
  serving_size?: number;
  cooking_time?: number;
  ingredients_with_qty?: string[];
  ingredients?: string[];
  cooking_method_array?: string[];
  image_link?: string;
  diet_type?: string[];
  allergens?: string[];
  devices?: string[];
  macros_per_serving?: MacrosPerServing;
}

export interface SubmitResponse {
  submission_id?: string;
  uuid?: string;
  status?: string;
  message?: string;
  error?: string;
}

export interface SubmissionsResponse {
  submissions?: RecipeSubmission[];
  count?: number;
  error?: string;
}

export interface PendingResponse {
  pending?: RecipeSubmission[];
  count?: number;
  error?: string;
}

export interface ApproveResponse {
  message?: string;
  food_id?: string;
  submission_id?: string;
  error?: string;
}

export interface RejectResponse {
  message?: string;
  submission_id?: string;
  error?: string;
}

// ============================================================================
// USER API Functions
// ============================================================================

/**
 * Submit a new recipe for admin approval
 */
export async function submitRecipe(
  user_id: string | null | undefined,
  data: RecipeSubmitData
): Promise<SubmitResponse | null> {
  try {
    if (!user_id) {
      return { error: "User ID is required" };
    }

    const response = await fetch(`${host}/api/recipe/submit?user_id=${user_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });

    const result: SubmitResponse = await response.json();

    if (!response.ok) {
      console.error("Submit Recipe error:", result.error);
      return result;
    }

    return result;
  } catch (error) {
    console.error("Submit Recipe error:", error);
    return { error: String(error) };
  }
}

/**
 * Get user's own recipe submissions
 */
export async function getMySubmissions(
  user_id: string | null | undefined,
  status?: string,
  limit: number = 20,
  offset: number = 0
): Promise<SubmissionsResponse | null> {
  try {
    if (!user_id) {
      return { error: "User ID is required" };
    }

    const params = new URLSearchParams({
      user_id,
      limit: String(limit),
      offset: String(offset),
    });
    if (status) {
      params.set("status", status);
    }

    const response = await fetch(`${host}/api/recipe/my-submissions?${params}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    const result: SubmissionsResponse = await response.json();

    if (!response.ok) {
      console.error("Get My Submissions error:", result.error);
      return result;
    }

    return result;
  } catch (error) {
    console.error("Get My Submissions error:", error);
    return { error: String(error) };
  }
}

// ============================================================================
// ADMIN API Functions
// ============================================================================

/**
 * [ADMIN] Get all pending recipe submissions
 */
export async function getPendingSubmissions(
  user_id: string | null | undefined,
  limit: number = 50,
  offset: number = 0
): Promise<PendingResponse | null> {
  try {
    if (!user_id) {
      return { error: "User ID is required" };
    }

    const params = new URLSearchParams({
      user_id,
      limit: String(limit),
      offset: String(offset),
    });

    const response = await fetch(`${host}/api/recipe/admin/pending?${params}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    const result: PendingResponse = await response.json();

    if (!response.ok) {
      console.error("Get Pending Submissions error:", result.error);
      return result;
    }

    return result;
  } catch (error) {
    console.error("Get Pending Submissions error:", error);
    return { error: String(error) };
  }
}

/**
 * [ADMIN] Get all recipe submissions with optional status filter
 */
export async function getAllSubmissions(
  user_id: string | null | undefined,
  status?: string,
  limit: number = 50,
  offset: number = 0
): Promise<SubmissionsResponse | null> {
  try {
    if (!user_id) {
      return { error: "User ID is required" };
    }

    const params = new URLSearchParams({
      user_id,
      limit: String(limit),
      offset: String(offset),
    });
    if (status) {
      params.set("status", status);
    }

    const response = await fetch(`${host}/api/recipe/admin/all?${params}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    const result: SubmissionsResponse = await response.json();

    if (!response.ok) {
      console.error("Get All Submissions error:", result.error);
      return result;
    }

    return result;
  } catch (error) {
    console.error("Get All Submissions error:", error);
    return { error: String(error) };
  }
}

/**
 * [ADMIN] Approve a recipe submission
 */
export async function approveSubmission(
  user_id: string | null | undefined,
  submission_id: string
): Promise<ApproveResponse | null> {
  try {
    if (!user_id) {
      return { error: "User ID is required" };
    }

    const response = await fetch(
      `${host}/api/recipe/admin/${submission_id}/approve?user_id=${user_id}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }
    );

    const result: ApproveResponse = await response.json();

    if (!response.ok) {
      console.error("Approve Submission error:", result.error);
      return result;
    }

    return result;
  } catch (error) {
    console.error("Approve Submission error:", error);
    return { error: String(error) };
  }
}

/**
 * [ADMIN] Reject a recipe submission
 */
export async function rejectSubmission(
  user_id: string | null | undefined,
  submission_id: string,
  reason: string
): Promise<RejectResponse | null> {
  try {
    if (!user_id) {
      return { error: "User ID is required" };
    }

    const response = await fetch(
      `${host}/api/recipe/admin/${submission_id}/reject?user_id=${user_id}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      }
    );

    const result: RejectResponse = await response.json();

    if (!response.ok) {
      console.error("Reject Submission error:", result.error);
      return result;
    }

    return result;
  } catch (error) {
    console.error("Reject Submission error:", error);
    return { error: String(error) };
  }
}
