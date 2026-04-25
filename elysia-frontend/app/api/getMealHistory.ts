import { host } from "@/app/components/host";
import { authHeaders } from "./authHeaders";

export interface MealHistoryResponse {
  user_id: string;
  logs: MealHistoryLog[];
  daily_totals: {
    [date: string]: {
      kcal: number;
      protein_g: number;
      fat_g: number;
      carb_g: number;
    };
  };
  total_logs: number;
  date_range: {
    start: string;
    end: string;
  };
  error: string;
}

export interface MealHistoryLog {
  log_id: string;
  user_id: string;
  logged_at: string;
  meal_description: string;
  parsed_dish?: string;
  ingredients?: any;
  portion_size?: number;
  calculated_macros: {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
  calculated_micros?: {
    [nutrient: string]: number;
  };
  validation_status?: string;
  parsing_method?: string;
}

export async function getMealHistory(
  user_id: string | null | undefined,
  days: number = 30,
  limit: number = 50,
  start_date?: string,
  end_date?: string,
): Promise<MealHistoryResponse | null> {
  const startTime = performance.now();
  try {
    if (!user_id) {
      return null;
    }

    const params = new URLSearchParams({
      days: days.toString(),
      limit: limit.toString(),
    });
    
    if (start_date) {
      params.append("start_date", start_date);
    }
    if (end_date) {
      params.append("end_date", end_date);
    }

    const response = await fetch(`${host}/db/${user_id}/meal_history?${params.toString()}`, {
      method: "GET",
      headers: authHeaders({ "Content-Type": "application/json" }),
    });

    if (!response.ok) {
      console.error(
        `Get Meal History error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: MealHistoryResponse = await response.json();
    
    if (data.error) {
      console.error("Get Meal History error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Get Meal History error:", error);
    return null;
  } finally {
    if (process.env.NODE_ENV === "development") {
      console.log(
        `meal_history took ${(performance.now() - startTime).toFixed(2)}ms`,
      );
    }
  }
}

