"use client";

/**
 * Backend HTTP host
 *
 * - Dev (non-static): default http://localhost:8000
 * - Prod (non-static): read from NEXT_PUBLIC_BACKEND_URL
 * - Static export: empty string → same origin as frontend
 *
 * QUAN TRỌNG: Khi dùng HTTPS qua Cloudflare, frontend PHẢI gọi qua cùng domain (qua Nginx proxy)
 * Nếu không có NEXT_PUBLIC_BACKEND_URL và đang HTTPS → dùng relative path (empty string)
 */
export const host = (() => {
  // Development mode: always use localhost:8000 unless overridden
  if (process.env.NODE_ENV === "development") {
    return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  }

  // Static mode: dùng relative path
  if (process.env.NEXT_PUBLIC_IS_STATIC === "true") {
    return "";
  }

  // Nếu có NEXT_PUBLIC_BACKEND_URL, dùng nó (ưu tiên cao nhất)
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }

  // Nếu đang chạy trên browser (client-side)
  if (typeof window !== "undefined") {
    // Nếu đang HTTPS → dùng full URL qua Nginx proxy
    if (window.location.protocol === "https:") {
      const currentHost = window.location.host;
      const fullUrl = `${window.location.protocol}//${currentHost}`;
      return fullUrl;
    }
    // Nếu đang HTTP → dùng localhost cho development
    return "http://localhost:8000";
  }

  // Server-side rendering: dùng localhost
  return "http://localhost:8000";
})();

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
