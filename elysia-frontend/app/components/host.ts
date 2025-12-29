"use client";

/**
 * Backend HTTP host
 *
 * - Dev (non-static): default http://localhost:8000
 * - Prod (non-static): read from NEXT_PUBLIC_BACKEND_URL
 * - Static export: empty string → same origin as frontend
 *
 * Điều này giúp bạn deploy trên IP thật (vd: http://57.158.27.105)
 * mà không bị hard-code localhost trong frontend.
 */
export const host =
  process.env.NEXT_PUBLIC_IS_STATIC !== "true"
    ? process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"
    : "";

export const public_path =
  process.env.NEXT_PUBLIC_IS_STATIC !== "true" ? "/" : "/static/";

/**
 * WebSocket base URL cho backend
 *
 * - Static export: dùng cùng IP/domain với frontend (window.location)
 * - Non-static: derive từ NEXT_PUBLIC_BACKEND_URL hoặc localhost:8000
 */
export const getWebsocketHost = () => {
  // Static mode: dùng đúng IP/domain mà người dùng đang truy cập
  if (process.env.NEXT_PUBLIC_IS_STATIC === "true") {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const current_host = window.location.host;
    return `${protocol}//${current_host}/ws/`;
  }

  // Helper: chuyển HTTP(S) backend URL → WS(S) URL
  const wsFromHttp = (backendUrl: string) => {
    try {
      const url = new URL(backendUrl);
      const protocol = url.protocol === "https:" ? "wss:" : "ws:";
      return `${protocol}//${url.host}/ws/`;
    } catch {
      // Fallback an toàn
      return "ws://localhost:8000/ws/";
    }
  };

  const backendUrl =
    process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  return wsFromHttp(backendUrl);
};
