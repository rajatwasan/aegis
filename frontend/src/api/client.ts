import createClient from "openapi-fetch";
import { loadApproverToken, needsApproverToken } from "../lib/approverToken";
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

/**
 * The approver credential rides only on the routes that resolve a decision or
 * ask who the viewer is (W2). It is read at request time so a token pasted
 * after the client was created is used on the very next action.
 */
api.use({
  onRequest({ request }) {
    if (!needsApproverToken(request.url)) return undefined;
    const token = loadApproverToken();
    if (token === "") return undefined;
    request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});
