/**
 * The approver credential at rest: an approver token issued by
 * `aegis approver add`, held only in this viewer's browser and sent as a
 * bearer header on the routes that resolve a decision or ask who the viewer
 * is (api/client.ts). No React here so the API client can import it without
 * a cycle (spec W2, decision D1).
 *
 * localStorage is a per viewer convenience so a reload does not sign the
 * reviewer out; reads and writes are wrapped because storage can be
 * unavailable in private mode, and the in memory value still works then.
 */
export const APPROVER_TOKEN_KEY = "aegis.approver_token";

export function loadApproverToken(): string {
  try {
    return window.localStorage.getItem(APPROVER_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function storeApproverToken(token: string): void {
  try {
    if (token === "") {
      window.localStorage.removeItem(APPROVER_TOKEN_KEY);
    } else {
      window.localStorage.setItem(APPROVER_TOKEN_KEY, token);
    }
  } catch {
    // private mode: the caller keeps the in memory value for this session
  }
}

/** Routes that carry the approver credential. Everything else stays anonymous. */
export function needsApproverToken(url: string): boolean {
  const path = new URL(url, "http://placeholder").pathname;
  return (
    path === "/approvers/me" ||
    /^\/proposals\/[^/]+\/(approve|reject)$/.test(path) ||
    path.startsWith("/guardian/")
  );
}
