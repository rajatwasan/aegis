import createClient from "openapi-fetch";
import type { paths } from "./schema";

export const API_URL: string =
  import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

/**
 * The one typed client every data fetch goes through. fetch is resolved at
 * call time (not client creation) so MSW's test interceptor, installed after
 * module import, still sees every request.
 */
export const api = createClient<paths>({
  baseUrl: API_URL,
  fetch: (input) => globalThis.fetch(input),
});
