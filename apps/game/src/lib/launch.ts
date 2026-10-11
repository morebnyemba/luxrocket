/**
 * Launch-token acquisition (doc 11 §3). Primary: postMessage handshake with the operator's SDK
 * (strict origin + source checks). Fallback: one-time token in the URL fragment, removed from
 * history immediately. Query-string tokens are never accepted.
 */

const HANDSHAKE_TIMEOUT_MS = 10_000;

function parentOrigin(): string | null {
  const ancestors = (window.location as Location & { ancestorOrigins?: DOMStringList }).ancestorOrigins;
  if (ancestors && ancestors.length > 0) return ancestors[0] ?? null;
  try {
    return document.referrer ? new URL(document.referrer).origin : null;
  } catch {
    return null;
  }
}

export function postToParent(type: string, data: Record<string, unknown> = {}): void {
  const origin = parentOrigin();
  if (window.parent === window || !origin) return;
  window.parent.postMessage({ lr: 1, type, data }, origin);
}

export async function acquireLaunchToken(): Promise<string> {
  const hash = new URLSearchParams(window.location.hash.slice(1));
  const fromFragment = hash.get("lt");
  if (fromFragment) {
    // Remove the token from the address bar and history before doing anything else.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return fromFragment;
  }
  if (window.parent === window) throw new Error("NO_LAUNCH_TOKEN");

  const origin = parentOrigin();
  if (!origin) throw new Error("PARENT_ORIGIN_UNKNOWN");
  const nonce = crypto.randomUUID();

  return new Promise<string>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMessage);
      reject(new Error("HANDSHAKE_TIMEOUT"));
    }, HANDSHAKE_TIMEOUT_MS);

    function onMessage(event: MessageEvent) {
      // Exact origin and source identity; schema-checked payload (doc 11 §5).
      if (event.origin !== origin || event.source !== window.parent) return;
      const msg = event.data as { lr?: number; type?: string; nonce?: string; data?: { launch_token?: unknown } };
      if (msg?.lr !== 1 || msg.type !== "LR_LAUNCH" || msg.nonce !== nonce) return;
      const token = msg.data?.launch_token;
      if (typeof token !== "string" || !token.startsWith("lt_")) return;
      window.clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      resolve(token);
    }

    window.addEventListener("message", onMessage);
    window.parent.postMessage({ lr: 1, type: "LR_READY", nonce, data: { protocol_versions: [1] } }, origin);
  });
}
