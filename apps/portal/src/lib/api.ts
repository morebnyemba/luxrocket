// Same-origin API client for /api/portal/v1. The session lives in an HttpOnly cookie the page
// cannot read; mutations carry X-LR-Portal, which the API requires (CSRF defence).

export const API = "/api/portal/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public detail = "",
  ) {
    super(detail || code);
  }
}

type StepUpHandler = () => Promise<boolean>;
let stepUpHandler: StepUpHandler | null = null;

/** The shell registers a dialog that asks for a TOTP code when an action needs step-up. */
export function onStepUp(handler: StepUpHandler | null) {
  stepUpHandler = handler;
}

async function request<T>(method: string, path: string, body?: unknown, retried = false): Promise<T> {
  const res = await fetch(`${API}/${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: method === "GET" ? {} : { "Content-Type": "application/json", "X-LR-Portal": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (res.ok) return data as T;
  const code = (data?.code as string) ?? `HTTP_${res.status}`;
  if (code === "STEP_UP_REQUIRED" && !retried && stepUpHandler && (await stepUpHandler())) {
    return request<T>(method, path, body, true);
  }
  if (typeof window !== "undefined") {
    // Full navigations on purpose: losing auth must drop every bit of in-memory page state.
    /* eslint-disable @next/next/no-location-assign-relative-destination */
    if (code === "UNAUTHENTICATED" || code === "MFA_REQUIRED") {
      window.location.assign(`/login${code === "MFA_REQUIRED" ? "?step=mfa" : ""}`);
    } else if (code === "PASSWORD_CHANGE_REQUIRED" && !window.location.pathname.startsWith("/account")) {
      window.location.assign("/account?first=1");
    }
    /* eslint-enable @next/next/no-location-assign-relative-destination */
  }
  throw new ApiError(res.status, code, (data?.detail as string) ?? "");
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
};

export const ERRORS: Record<string, string> = {
  INVALID_CREDENTIALS: "Email or password is incorrect.",
  ACCOUNT_LOCKED: "Too many attempts. The account is locked for 15 minutes.",
  INVALID_CODE: "That code is not valid. Codes can be used once.",
  MFA_ENROLLMENT_REQUIRED: "Set up two-factor authentication in Account before doing this.",
  STEP_UP_REQUIRED: "Confirm with your authenticator code to continue.",
  FORBIDDEN: "Your role does not allow this.",
  CREDENTIAL_LIMIT: "Two keys are already active. Revoke one first.",
  LAST_ACTIVE_KEY: "Add the replacement key before revoking the last one.",
  CONFIG_NOT_PERMITTED: "That setting is outside what the platform allows.",
  WEAK_PASSWORD: "Use at least 12 characters, different from the current password.",
  ALREADY_EXISTS: "A user with that email already exists.",
  WALLET_NOT_CONFIGURED: "Configure a wallet URL first.",
};

export function message(err: unknown): string {
  if (err instanceof ApiError) return ERRORS[err.code] ?? (err.detail || err.code);
  return "Something went wrong. Try again.";
}
