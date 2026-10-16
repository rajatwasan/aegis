import { useState } from "react";
import { useApproverMe } from "../api/queries";
import { loadApproverToken, storeApproverToken } from "./approverToken";

/**
 * React side of the approver credential (see approverToken.ts for the
 * storage and routing rules). The server says who the token belongs to;
 * nothing about identity is typed by hand (spec W2, decision D1).
 */
export function useApproverToken(): [string, (token: string) => void] {
  const [token, setToken] = useState(loadApproverToken);
  const update = (next: string) => {
    const trimmed = next.trim();
    setToken(trimmed);
    storeApproverToken(trimmed);
  };
  return [token, update];
}

/** The resolved identity, or null when the viewer cannot act (W2). */
export function useResolvedApprover(token: string): {
  canAct: boolean;
  displayName: string | null;
} {
  const me = useApproverMe(token);
  return {
    canAct: me.data !== undefined,
    displayName: me.data?.display_name ?? null,
  };
}
