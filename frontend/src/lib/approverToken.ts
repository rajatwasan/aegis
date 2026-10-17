import { useState } from "react";

/**
 * The approver's credential: a bearer token the operator typed, stored under
 * one localStorage key and sent only as `Authorization: Bearer` on approve and
 * reject (AGENTS.md R33). The server derives the approver identity from it;
 * the browser never names the approver itself. Guardian signing stays
 * server side.
 */
export const STORAGE_KEY = "aegis.approver_token";

export function loadApproverToken(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function useApproverToken(): [string, (token: string) => void] {
  const [token, setToken] = useState(loadApproverToken);
  const update = (next: string) => {
    setToken(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // private mode: the in-memory value still works for this session
    }
  };
  return [token, update];
}
