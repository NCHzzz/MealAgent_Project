import { host } from "@/app/components/host";

export async function updateObject(
  user_id: string,
  collection_name: string,
  uuid: string,
  data: any
) {
  const startTime = performance.now();
  try {
    const response = await fetch(
      `${host}/collections/${user_id}/update_object/${collection_name}/${uuid}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
      }
    );

    if (!response.ok) {
      console.error(
        `Error updating object! status: ${response.status} ${response.statusText}`
      );
      return {
        error: "Error updating object",
      };
    }

    const result = await response.json();
    return result;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return {
      error: "Error updating object",
    };
  } finally {
    if (process.env.NODE_ENV === "development") {
      console.log(
        `collections/update_object took ${(performance.now() - startTime).toFixed(2)}ms`
      );
    }
  }
}
