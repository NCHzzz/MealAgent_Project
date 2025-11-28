import { host } from "@/app/components/host";
import { UserProfile } from "@/app/types/profile";

export type ProfileApiResponse = {
  error: string;
  profile: UserProfile | null;
};

export async function fetchUserProfile(
  user_id: string
): Promise<ProfileApiResponse> {
  try {
    const response = await fetch(`${host}/mealagent/profile/${user_id}`, {
      method: "GET",
    });
    if (!response.ok) {
      const errorText = await response.text();
      return { error: errorText || "Failed to fetch profile", profile: null };
    }
    const data = (await response.json()) as ProfileApiResponse;
    return data;
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : "Failed to fetch profile",
      profile: null,
    };
  }
}

export async function saveUserProfile(
  user_id: string,
  profile: Partial<UserProfile>
): Promise<ProfileApiResponse> {
  try {
    const response = await fetch(`${host}/mealagent/profile/${user_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      return { error: errorText || "Failed to save profile", profile: null };
    }
    const data = (await response.json()) as ProfileApiResponse;
    return data;
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : "Failed to save profile",
      profile: null,
    };
  }
}


