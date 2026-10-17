"use client";

import { useCallback, useEffect, useState } from "react";

import { message, type Api } from "./api";

export type Resource<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

/** GET a resource; state is only set from the async result (no sync setState in effects). */
export function useResource<T>(api: Api, path: string | null): Resource<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; key: string | null }>({
    data: null,
    error: null,
    key: null,
  });
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (path === null) return;
    let live = true;
    const key = `${path}#${nonce}`;
    api.get<T>(path).then(
      (data) => {
        if (live) setState({ data, error: null, key });
      },
      (err: unknown) => {
        if (live) setState((s) => ({ data: s.data, error: message(err), key }));
      },
    );
    return () => {
      live = false;
    };
  }, [api, path, nonce]);

  const loading = path !== null && state.key !== `${path}#${nonce}`;
  return { data: state.data, error: state.error, loading, reload };
}
