import { host } from "@/app/components/host";

export interface AcceptPlanResponse {
  success: boolean;
  message?: string;
  error?: string;
}

export async function acceptPlan(
  userId: string | undefined,
  planId: string | undefined,
): Promise<AcceptPlanResponse> {
  if (!userId || !planId) {
    return { success: false, error: "missing userId or planId" };
  }

  try {
    const response = await fetch(`${host}/db/${userId}/accept_plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: planId }),
    });

    if (!response.ok) {
      return {
        success: false,
        error: `Accept plan failed: ${response.status} ${response.statusText}`,
      };
    }

    const data = (await response.json()) as AcceptPlanResponse;
    if (data.error) {
      return { success: false, error: data.error };
    }

    return { success: data.success !== false, message: data.message };
  } catch (error) {
    return { success: false, error: (error as Error).message };
  }
}

