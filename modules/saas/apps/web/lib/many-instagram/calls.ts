import { manyRequest, type ManyScope } from "@/lib/many";

/** Instagram calls that do not filter by workspace use the staff scope. */
export const STAFF: ManyScope = { kind: "staff" };

export function staffGet<T>(path: string) {
  return manyRequest<T>(STAFF, "GET", path);
}
export function staffSend<T>(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
) {
  return manyRequest<T>(STAFF, method, path, body);
}
