import { host } from "@/app/components/host";

export async function addObject(
  user_id: string,
  collection_name: string,
  data: any
) {
  const startTime = performance.now();
  try {
    const response = await fetch(
      `${host}/collections/${user_id}/add_object/${collection_name}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
      }
    );

    if (!response.ok) {
      console.error(
        `Error adding object! status: ${response.status} ${response.statusText}`
      );
      return {
        error: "Error adding object",
      };
    }

    const result = await response.json();
    return result;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return {
      error: "Error adding object",
    };
  } finally {
    if (process.env.NODE_ENV === "development") {
      console.log(
        `collections/add_object took ${(performance.now() - startTime).toFixed(2)}ms`
      );
    }
  }
}
