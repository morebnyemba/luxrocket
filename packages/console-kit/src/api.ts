// Same-origin JSON client for the consoles (operator portal, platform admin). Sessions live in
// HttpOnly cookies the page cannot read; mutations carry X-LR-Portal, which both APIs require.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public detail = "",
  ) {
    super(detail || code);
  }
}

export type StepUpHandler = () => Promise<boolean>;

export type ApiOptions = {
  /** Called for auth-loss codes (e.g. UNAUTHENTICATED); typically a full navigation to login. */
  onAuthLost: (code: string) => void;
  /** Codes that mean "authenticate again" for this console. */
  authLostCodes: string[];
};

export type Api = {
  get: <T>(path: string) => Promise<T>;
  post: <T>(path: string, body?: unknown) => Promise<T>;
  put: <T>(path: string, body: unknown) => Promise<T>;
  patch: <T>(path: string, body: unknown) => Promise<T>;
  onStepUp: (handler: StepUpHandler | null) => void;
};

export function createApi(base: string, options: ApiOptions): Api {
  let stepUp: StepUpHandler | null = null;

  async function request<T>(method: string, path: string, body?: unknown, retried = false): Promise<T> {
    const res = await fetch(`${base}/${path}`, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: method === "GET" ? {} : { "Content-Type": "application/json", "X-LR-Portal": "1" },
      body: body === undefined ? null : JSON.stringify(body),
    });
    const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
    if (res.ok) return data as T;
    const code = (data?.code as string | undefined) ?? `HTTP_${res.status}`;
    if (code === "STEP_UP_REQUIRED" && !retried && stepUp && (await stepUp())) {
      return request<T>(method, path, body, true);
    }
    if (options.authLostCodes.includes(code)) options.onAuthLost(code);
    throw new ApiError(res.status, code, (data?.detail as string | undefined) ?? "");
  }

  return {
    get: <T>(path: string) => request<T>("GET", path),
    post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
    put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
    patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
    onStepUp: (handler) => {
      stepUp = handler;
    },
  };
}

export const ERRORS: Record<string, string> = {
  INVALID_CREDENTIALS: "Email or password is incorrect.",
  ACCOUNT_LOCKED: "Too many attempts. The account is locked for 15 minutes.",
  INVALID_CODE: "That code is not valid. Codes can be used once.",
  MFA_ENROLLMENT_REQUIRED: "Set up two-factor authentication in Account before doing this.",
  STEP_UP_REQUIRED: "Confirm it's you to continue.",
  FORBIDDEN: "Your role does not allow this.",
  CREDENTIAL_LIMIT: "Two keys are already active. Revoke one first.",
  LAST_ACTIVE_KEY: "Add the replacement key before revoking the last one.",
  CONFIG_NOT_PERMITTED: "That setting is outside what the platform allows.",
  WEAK_PASSWORD: "Use a longer password, different from the current one.",
  ALREADY_EXISTS: "That already exists.",
  WALLET_NOT_CONFIGURED: "Configure a wallet URL first.",
  PASSKEY_INVALID: "The security key response was not accepted.",
  CHALLENGE_EXPIRED: "That took too long. Try again.",
  SELF_APPROVAL: "You cannot decide your own request — another person must.",
  NOTE_REQUIRED: "A note is required.",
  REASON_REQUIRED: "A reason is required.",
  EVIDENCE_REQUIRED: "Real-money markets need an evidence reference.",
  SUPERADMIN_CAP: "There are already three superadmins.",
  ALREADY_PENDING: "A request for this is already pending.",
};

export function message(err: unknown): string {
  if (err instanceof ApiError) return ERRORS[err.code] ?? (err.detail || err.code);
  if (err instanceof Error && err.name === "NotAllowedError") return "The security key prompt was cancelled.";
  return "Something went wrong. Try again.";
}
