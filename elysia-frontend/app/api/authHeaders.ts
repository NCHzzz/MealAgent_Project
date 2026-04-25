const STORAGE_KEY = "elysia_auth_user";

export function getStoredAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const cached = window.localStorage.getItem(STORAGE_KEY);
    if (!cached) return null;
    const parsed = JSON.parse(cached) as { token?: string };
    return parsed.token || null;
  } catch {
    return null;
  }
}

export function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getStoredAuthToken();
  return {
    ...(extra || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export function appendAuthToken(url: string): string {
  const token = getStoredAuthToken();
  if (!token) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(token)}`;
}
