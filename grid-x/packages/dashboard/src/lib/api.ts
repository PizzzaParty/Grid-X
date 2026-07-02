export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Default headers for all API requests.
 * The ngrok header bypasses the browser warning page when tunneling via ngrok.
 * Safe to include in production — unknown headers are ignored by real servers.
 */
export const API_HEADERS: HeadersInit = {
  "ngrok-skip-browser-warning": "true",
};

