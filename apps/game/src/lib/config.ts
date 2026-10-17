/** Build-time configuration (static export; NEXT_PUBLIC_* values are inlined). */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const RT_URL = process.env.NEXT_PUBLIC_RT_URL ?? "ws://localhost:4000/socket";
