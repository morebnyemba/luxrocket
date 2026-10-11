// Portal instance of the shared console client (same origin, /api/portal/v1).
import { createApi } from "@luxrocket/console-kit";

export { ApiError, ERRORS, message } from "@luxrocket/console-kit";

export const API = "/api/portal/v1";

export const api = createApi(API, {
  authLostCodes: ["UNAUTHENTICATED", "MFA_REQUIRED", "PASSWORD_CHANGE_REQUIRED"],
  // Full navigations on purpose: losing auth must drop every bit of in-memory page state.
  /* eslint-disable @next/next/no-location-assign-relative-destination */
  onAuthLost: (code) => {
    if (code === "PASSWORD_CHANGE_REQUIRED") {
      if (!window.location.pathname.startsWith("/account")) window.location.assign("/account?first=1");
      return;
    }
    window.location.assign(`/login${code === "MFA_REQUIRED" ? "?step=mfa" : ""}`);
  },
  /* eslint-enable @next/next/no-location-assign-relative-destination */
});

export const onStepUp = api.onStepUp;
