import { api } from "./api";
import { createPasskey, getPasskey } from "./webauthn";

/** Passkey assertion: completes sign-in, or refreshes step-up when already signed in. */
export async function verifyWithPasskey(): Promise<{ must_change_password: boolean }> {
  const options = await api.post<unknown>("auth/passkey/options");
  const credential = await getPasskey(options);
  return api.post("auth/passkey/verify", { credential });
}

export async function registerPasskey(name: string): Promise<{ must_change_password: boolean }> {
  const options = await api.post<unknown>("auth/passkey/register/options");
  const credential = await createPasskey(options);
  return api.post("auth/passkey/register", { credential, name });
}

export type Me = {
  email: string;
  role: string;
  stage: string;
  must_change_password: boolean;
  step_up_valid: boolean;
  permissions: string[];
  passkeys: { id: string; name: string; created_at: string; last_used_at: string | null }[];
};
