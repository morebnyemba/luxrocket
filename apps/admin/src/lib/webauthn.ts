// navigator.credentials <-> the JSON the API speaks (base64url for every binary field).

const toBuf = (s: string): ArrayBuffer => {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
};

const toB64url = (buf: ArrayBuffer): string =>
  btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

type Desc = { id: string; type: "public-key"; transports?: AuthenticatorTransport[] };

/* eslint-disable @typescript-eslint/no-explicit-any */
export async function createPasskey(options: any): Promise<unknown> {
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...options,
    challenge: toBuf(options.challenge),
    user: { ...options.user, id: toBuf(options.user.id) },
    excludeCredentials: (options.excludeCredentials ?? []).map((c: Desc) => ({ ...c, id: toBuf(c.id) })),
  };
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential;
  const r = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id,
    rawId: toB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: toB64url(r.clientDataJSON),
      attestationObject: toB64url(r.attestationObject),
      transports: r.getTransports?.() ?? [],
    },
  };
}

export async function getPasskey(options: any): Promise<unknown> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...options,
    challenge: toBuf(options.challenge),
    allowCredentials: (options.allowCredentials ?? []).map((c: Desc) => ({ ...c, id: toBuf(c.id) })),
  };
  const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential;
  const r = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: toB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: toB64url(r.clientDataJSON),
      authenticatorData: toB64url(r.authenticatorData),
      signature: toB64url(r.signature),
      userHandle: r.userHandle ? toB64url(r.userHandle) : null,
    },
  };
}
/* eslint-enable @typescript-eslint/no-explicit-any */
