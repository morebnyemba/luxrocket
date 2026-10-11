"use client";

import { useResource as useKitResource, type Resource } from "@luxrocket/console-kit";

import { api } from "./api";

export type { Resource };

export function useResource<T>(path: string | null): Resource<T> {
  return useKitResource<T>(api, path);
}
