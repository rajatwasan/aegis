/**
 * Guardian passkey data hooks. These live beside the page rather than in
 * api/queries.ts because each flow interleaves a device WebAuthn ceremony
 * between two API calls; the calls themselves still go through the
 * generated openapi-fetch client.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  startAuthentication,
  startRegistration,
  type AuthenticationResponseJSON,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
  type RegistrationResponseJSON,
} from "@simplewebauthn/browser";
import { api } from "../../api/client";
import { unwrap } from "../../api/queries";
import type { ProposalRow } from "../../api/types";
import { savePairing, type PairingState } from "./pairing";

/** py_webauthn emits spec WebAuthn JSON; narrow the loose schema shape here. */
function asCreationOptions(
  value: Record<string, unknown>,
): PublicKeyCredentialCreationOptionsJSON {
  return value as unknown as PublicKeyCredentialCreationOptionsJSON;
}

function asRequestOptions(
  value: Record<string, unknown>,
): PublicKeyCredentialRequestOptionsJSON {
  return value as unknown as PublicKeyCredentialRequestOptionsJSON;
}

function asBody(
  credential: RegistrationResponseJSON | AuthenticationResponseJSON,
): Record<string, unknown> {
  return credential as unknown as Record<string, unknown>;
}

/** Pair this device: code -> registration options -> passkey -> complete. */
export function usePairDevice() {
  return useMutation({
    mutationFn: async (code: string): Promise<PairingState> => {
      const options = asCreationOptions(
        await unwrap(api.POST("/guardian/pair/options", { body: { code } })),
      );
      const credential = await startRegistration({ optionsJSON: options });
      const done = await unwrap(
        api.POST("/guardian/pair/complete", {
          body: { code, credential: asBody(credential) },
        }),
      );
      const state: PairingState = { paired: true, credentialId: done.credential_id };
      savePairing(state);
      return state;
    },
  });
}

/**
 * The Face ID step, separate from the decide mutation so the card stays
 * visible (not optimistically removed) while the user is still confirming.
 */
export async function requestAssertion(
  decisionId: string,
): Promise<AuthenticationResponseJSON> {
  const options = asRequestOptions(
    await unwrap(
      api.POST("/guardian/auth-options/{proposal_id}", {
        params: { path: { proposal_id: decisionId } },
      }),
    ),
  );
  return startAuthentication({ optionsJSON: options });
}

export interface GuardianDecision {
  decisionId: string;
  action: "approve" | "reject";
  comment: string;
  credential: AuthenticationResponseJSON;
}

/**
 * Submit a verified decision with optimistic removal from the pending list
 * and rollback on failure — the same cache contract the desktop approvals
 * screen uses, so both stay consistent under SSE invalidation.
 */
export function useGuardianDecide() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ decisionId, action, comment, credential }: GuardianDecision) =>
      unwrap(
        api.POST("/guardian/decide/{proposal_id}", {
          params: { path: { proposal_id: decisionId } },
          body: { action, comment, credential: asBody(credential) },
        }),
      ),
    onMutate: async ({ decisionId }) => {
      await queryClient.cancelQueries({ queryKey: ["proposals", "pending"] });
      const previous = queryClient.getQueryData<ProposalRow[]>([
        "proposals",
        "pending",
      ]);
      queryClient.setQueryData<ProposalRow[]>(
        ["proposals", "pending"],
        (rows) => rows?.filter((r) => r.decision_id !== decisionId) ?? [],
      );
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(["proposals", "pending"], context.previous);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["proposals"] });
      void queryClient.invalidateQueries({ queryKey: ["metrics"] });
    },
  });
}
