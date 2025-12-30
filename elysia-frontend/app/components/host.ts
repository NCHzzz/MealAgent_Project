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
 * 
 * QUAN TRỌNG: Nếu trang load qua HTTPS, WebSocket PHẢI dùng WSS (không được dùng WS)
 */
export const getWebsocketHost = () => {
  // Luôn detect protocol từ window.location (trang hiện tại)
  // Nếu trang load qua HTTPS → PHẢI dùng WSS
  const isHttps = typeof window !== "undefined" && window.location.protocol === "https:";
  const wsProtocol = isHttps ? "wss:" : "ws:";

  // Static mode: dùng đúng IP/domain mà người dùng đang truy cập
  if (process.env.NEXT_PUBLIC_IS_STATIC === "true") {
    const current_host = window.location.host;
    return `${wsProtocol}//${current_host}/ws/`;
  }

  // Helper: chuyển HTTP(S) backend URL → WS(S) URL
  const wsFromHttp = (backendUrl: string) => {
    try {
      const url = new URL(backendUrl);
      // QUAN TRỌNG: Nếu trang load qua HTTPS, luôn dùng WSS
      // (ngay cả khi backend URL là HTTP, Cloudflare sẽ proxy WSS → WS)
      if (isHttps) {
        // Trang load qua HTTPS → luôn dùng WSS với cùng host
        // Cloudflare sẽ proxy WSS → WS đến backend
        return `wss://${url.host}/ws/`;
      }
      // Trang load qua HTTP → dùng WS hoặc WSS tùy backend URL
      const protocol = url.protocol === "https:" ? "wss:" : "ws:";
      return `${protocol}//${url.host}/ws/`;
    } catch {
      // Fallback: nếu trang load qua HTTPS → dùng WSS với localhost
      // (cho development với HTTPS local)
      if (isHttps) {
        return "wss://localhost:8000/ws/";
      }
      return "ws://localhost:8000/ws/";
    }
  };

  const backendUrl =
    process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  // Nếu trang load qua HTTPS và không có NEXT_PUBLIC_BACKEND_URL
  // → dùng cùng host với frontend (Cloudflare sẽ proxy)
  if (isHttps && !process.env.NEXT_PUBLIC_BACKEND_URL) {
    const current_host = window.location.host;
    return `wss://${current_host}/ws/`;
  }

  return wsFromHttp(backendUrl);
};
