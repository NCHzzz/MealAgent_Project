import { host } from "@/app/components/host";

export interface ShoppingItem {
  list_id: string;
  ingredient_name: string;
  quantity: number;
  unit: string;
  category?: string;
  purchased: boolean;
}

export interface ShoppingList {
  list_id: string;
  user_id: string;
  plan_id?: string;
  plan_start_date?: string;  // Start date of the plan
  created_at?: string;
  items?: ShoppingItem[];
  item_count?: number;
}

export interface ShoppingResponse {
  lists?: ShoppingList[];
  items?: ShoppingItem[];
  error?: string;
}

export async function getShoppingLists(
  user_id: string | null | undefined,
  list_id?: string,
): Promise<ShoppingResponse | null> {
  const startTime = performance.now();
  try {
    if (!user_id) {
      return null;
    }

    const url = list_id
      ? `${host}/db/${user_id}/shopping?action=read&list_id=${encodeURIComponent(list_id)}`
      : `${host}/db/${user_id}/shopping?action=read`;

    const response = await fetch(url, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      console.error(
        `Get Shopping Lists error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: ShoppingResponse = await response.json();
    
    if (data.error) {
      console.error("Get Shopping Lists error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Get Shopping Lists error:", error);
    return null;
  } finally {
    if (process.env.NODE_ENV === "development") {
      console.log(
        `get_shopping_lists took ${(performance.now() - startTime).toFixed(2)}ms`,
      );
    }
  }
}

export async function createShoppingItems(
  user_id: string | null | undefined,
  list_id: string,
  items: ShoppingItem[],
): Promise<ShoppingResponse | null> {
  try {
    if (!user_id || !list_id) {
      return null;
    }

    const response = await fetch(
      `${host}/db/${user_id}/shopping?action=create&list_id=${encodeURIComponent(list_id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_id, shopping_items: items }),
      },
    );

    if (!response.ok) {
      console.error(
        `Create Shopping Items error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: ShoppingResponse = await response.json();
    
    if (data.error) {
      console.error("Create Shopping Items error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Create Shopping Items error:", error);
    return null;
  }
}

export async function updateShoppingItems(
  user_id: string | null | undefined,
  list_id: string,
  items: ShoppingItem[],
): Promise<ShoppingResponse | null> {
  try {
    if (!user_id || !list_id) {
      return null;
    }

    const response = await fetch(
      `${host}/db/${user_id}/shopping?action=update&list_id=${encodeURIComponent(list_id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_id, shopping_items: items }),
      },
    );

    if (!response.ok) {
      console.error(
        `Update Shopping Items error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: ShoppingResponse = await response.json();
    
    if (data.error) {
      console.error("Update Shopping Items error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Update Shopping Items error:", error);
    return null;
  }
}

export async function deleteShoppingItems(
  user_id: string | null | undefined,
  list_id: string,
  items?: ShoppingItem[],
): Promise<ShoppingResponse | null> {
  try {
    if (!user_id || !list_id) {
      return null;
    }

    const response = await fetch(
      `${host}/db/${user_id}/shopping?action=delete&list_id=${encodeURIComponent(list_id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_id, shopping_items: items || [] }),
      },
    );

    if (!response.ok) {
      console.error(
        `Delete Shopping Items error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: ShoppingResponse = await response.json();
    
    if (data.error) {
      console.error("Delete Shopping Items error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Delete Shopping Items error:", error);
    return null;
  }
}

export async function togglePurchased(
  user_id: string | null | undefined,
  list_id: string,
  items: ShoppingItem[],
): Promise<ShoppingResponse | null> {
  try {
    if (!user_id || !list_id) {
      return null;
    }

    const response = await fetch(
      `${host}/db/${user_id}/shopping?action=toggle_purchased&list_id=${encodeURIComponent(list_id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list_id, shopping_items: items }),
      },
    );

    if (!response.ok) {
      console.error(
        `Toggle Purchased error! status: ${response.status} ${response.statusText}`,
      );
      return null;
    }

    const data: ShoppingResponse = await response.json();
    
    if (data.error) {
      console.error("Toggle Purchased error:", data.error);
      return null;
    }
    
    return data;
  } catch (error) {
    console.error("Toggle Purchased error:", error);
    return null;
  }
}

