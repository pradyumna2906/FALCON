import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "../auth/session";
import { api, ApiError } from "./client";
import type { components } from "./generated";

export type Schema<T extends keyof components["schemas"]> =
  components["schemas"][T];
export function useResource<T>(path: string, enabled = true) {
  const { user, status } = useSession();
  return useQuery({
    queryKey: ["finance", user?.id, path],
    enabled: enabled && status === "authenticated" && !!user?.email_verified,
    queryFn: ({ signal }) => api.request<T>(path, { signal }),
  });
}
export function useFinanceMutation() {
  const cache = useQueryClient();
  return async <T>(
    path: string,
    method: string,
    body?: unknown,
  ): Promise<T> => {
    const result = await api.request<T>(path, {
      method,
      body:
        body instanceof FormData
          ? body
          : body === undefined
            ? undefined
            : JSON.stringify(body),
    });
    await cache.invalidateQueries({ queryKey: ["finance"] });
    return result;
  };
}
export function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? `${error.message}${error.requestId ? ` Reference: ${error.requestId}` : ""}`
    : "Unable to connect. Check your connection; verify whether the change was saved before retrying.";
}
// Exact decimal presentation: no Number conversion or frontend balance arithmetic.
export function money(value: string | null | undefined, currency: string) {
  if (value == null) return "Unavailable";
  const [whole, fraction] = value.split(".");
  return `${currency} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction ? `.${fraction}` : ""}`;
}
export function localDate(timezone = "Asia/Kolkata") {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}
