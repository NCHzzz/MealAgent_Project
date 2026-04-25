import { host } from "@/app/components/host";
import { authHeaders } from "./authHeaders";

export interface PantryItem {
  pantry_item_id?: string;
  ingredient_name: string;
  quantity: number;
  unit: string;
  fdc_id?: number;
  expiry_date?: string;
}

export interface PantryState {
  user_id: string;
  items: PantryItem[];
  item_count: number;
}

export interface PantryResponse {
  state?: PantryState;
  items?: PantryItem[];
  error?: string;
}

export async function getPantry(
  user_id: string | null | undefined,
): Promise<PantryResponse | null> {
  const startTime = performance.now();
  try {
    if (!user_id) {
      return null;
    }

    const response = await fetch(`${host}/db/${user_id}/pantry?action=read`, {
      method: "GET",
      headers: authHeaders({ "Content-Type": "application/json" }),
    });

    if (!response.ok) {
      console.error(
        `Get Pantry error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: PantryResponse = await response.json();
    
    if (data.error) {
      console.error("Get Pantry error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Get Pantry error:", error);
    return null;
  } finally {
    if (process.env.NODE_ENV === "development") {
      console.log(
        `get_pantry took ${(performance.now() - startTime).toFixed(2)}ms`,
      );
    }
  }
}

export async function createPantryItems(
  user_id: string | null | undefined,
  items: PantryItem[],
): Promise<PantryResponse | null> {
  try {
    if (!user_id) {
      return null;
    }

    const response = await fetch(`${host}/db/${user_id}/pantry?action=create`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ pantry_items: items }),
    });

    if (!response.ok) {
      console.error(
        `Create Pantry Items error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: PantryResponse = await response.json();
    
    if (data.error) {
      console.error("Create Pantry Items error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Create Pantry Items error:", error);
    return null;
  }
}

export async function updatePantryItems(
  user_id: string | null | undefined,
  items: PantryItem[],
): Promise<PantryResponse | null> {
  try {
    if (!user_id) {
      return null;
    }

    const response = await fetch(`${host}/db/${user_id}/pantry?action=update`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ pantry_items: items }),
    });

    if (!response.ok) {
      console.error(
        `Update Pantry Items error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: PantryResponse = await response.json();
    
    if (data.error) {
      console.error("Update Pantry Items error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Update Pantry Items error:", error);
    return null;
  }
}

export async function deletePantryItems(
  user_id: string | null | undefined,
  items: PantryItem[],
): Promise<PantryResponse | null> {
  try {
    if (!user_id) {
      return null;
    }

    const response = await fetch(`${host}/db/${user_id}/pantry?action=delete`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ pantry_items: items }),
    });

    if (!response.ok) {
      console.error(
        `Delete Pantry Items error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: PantryResponse = await response.json();
    
    if (data.error) {
      console.error("Delete Pantry Items error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Delete Pantry Items error:", error);
    return null;
  }
}

