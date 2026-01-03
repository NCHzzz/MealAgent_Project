import { host } from "@/app/components/host";

export async function deleteObject(
  user_id: string,
  collection_name: string,
  uuid: string
) {
  const startTime = performance.now();
  try {
    const response = await fetch(
      `${host}/collections/${user_id}/delete_object/${collection_name}/${uuid}`,
      {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
        },
      }
    );

    if (!response.ok) {
      console.error(
        `Error deleting object! status: ${response.status} ${response.statusText}`
      );
      return {
        error: "Error deleting object",
      };
    }

    const result = await response.json();
    return result;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return {
      error: "Error deleting object",
    };
  } finally {
    if (process.env.NODE_ENV === "development") {
      console.log(
        `collections/delete_object took ${(performance.now() - startTime).toFixed(2)}ms`
      );
    }
  }
}
