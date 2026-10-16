/** Pairing state (localStorage) + WebAuthn error prose for the phone flow. */

const STORAGE_KEY = "aegis.guardian";

export interface PairingState {
  paired: true;
  credentialId: string;
  /** the approver this passkey is bound to, as the server reported at pairing (W10) */
  approverId: string;
  displayName: string;
}

export function loadPairing(): PairingState | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return null;
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" &&
      value !== null &&
      "paired" in value &&
      (value as { paired: unknown }).paired === true &&
      "credentialId" in value &&
      typeof (value as { credentialId: unknown }).credentialId === "string" &&
      "approverId" in value &&
      typeof (value as { approverId: unknown }).approverId === "string" &&
      "displayName" in value &&
      typeof (value as { displayName: unknown }).displayName === "string"
    ) {
      return value as PairingState;
    }
    // a pairing saved before passkeys were bound to an approver: pair again
    return null;
  } catch {
    return null;
  }
}

export function savePairing(state: PairingState): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

/**
 * WebAuthn failures are cryptic DOMExceptions ("NotAllowedError: The
 * operation either timed out or was not allowed") — always surface the name
 * alongside the message so they can be diagnosed from a phone screenshot.
 */
export function describeWebAuthnError(error: unknown): string {
  if (error instanceof Error) {
    const name = error.name !== "" && error.name !== "Error" ? `${error.name}: ` : "";
    return `${name}${error.message}`;
  }
  return String(error);
}
