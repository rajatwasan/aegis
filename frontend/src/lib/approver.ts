import { useState } from "react";

/**
 * The reviewer's identity: a simple client-side setting (guardian signing
 * stays server-side by design). Persisted so it survives reloads and sent
 * as the `approver` field on approve/reject (ADR 003).
 */
const STORAGE_KEY = "aegis.approver";

export function loadApprover(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function useApprover(): [string, (name: string) => void] {
  const [name, setName] = useState(loadApprover);
  const update = (next: string) => {
    setName(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // private mode: the in-memory value still works for this session
    }
  };
  return [name, update];
}
