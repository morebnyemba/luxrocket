// Admin instance of the shared console client (same origin, /api/admin/v1).
import { createApi } from "@luxrocket/console-kit";

export { ApiError, message } from "@luxrocket/console-kit";

export const api = createApi("/api/admin/v1", {
  authLostCodes: ["UNAUTHENTICATED", "PASSKEY_REQUIRED", "PASSKEY_ENROLLMENT_REQUIRED"],
  // Full navigation on purpose: losing auth drops all in-memory state.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  onAuthLost: () => window.location.assign("/login"),
});
