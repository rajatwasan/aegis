/**
 * TanStack Query hooks — every server read/write in the app lives here and
 * goes through the generated openapi-fetch client. Query keys line up with
 * `invalidationsFor` in lib/events.ts so the SSE stream keeps them fresh.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { asProposalRow, asProposalRows, type ProposalRow } from "./types";

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined || data === undefined) {
    const detail =
      typeof error === "object" && error !== null && "detail" in error
        ? String((error as { detail: unknown }).detail)
        : `request failed (${response.status})`;
    // a 401 on an action means the approver token was missing or rejected (W2)
    throw new ApiError(
      response.status === 401 ? `token rejected: ${detail}` : detail,
      response.status,
    );
  }
  return data;
}

// ------------------------------------------------------------------- reads

export function useMetrics() {
  return useQuery({
    queryKey: ["metrics"],
    queryFn: () => unwrap(api.GET("/metrics")),
    refetchInterval: 30_000, // SSE invalidates faster; this is the safety net
  });
}

export function usePendingProposals() {
  return useQuery({
    queryKey: ["proposals", "pending"],
    queryFn: async () =>
      asProposalRows(
        await unwrap(
          api.GET("/proposals", { params: { query: { status: "pending" } } }),
        ),
      ),
  });
}

export function useProposal(decisionId: string | null) {
  return useQuery({
    queryKey: ["proposals", "detail", decisionId],
    enabled: decisionId !== null,
    queryFn: async () =>
      asProposalRow(
        await unwrap(
          api.GET("/proposals/{decision_id}", {
            params: { path: { decision_id: decisionId ?? "" } },
          }),
        ),
      ),
  });
}

export function useDecisions(limit = 50, offset = 0) {
  return useQuery({
    queryKey: ["decisions", limit, offset],
    queryFn: () =>
      unwrap(api.GET("/decisions", { params: { query: { limit, offset } } })),
  });
}

export function useAuditRecords(limit: number, offset: number) {
  return useQuery({
    queryKey: ["audit", "records", limit, offset],
    queryFn: () =>
      unwrap(
        api.GET("/audit/records", { params: { query: { limit, offset } } }),
      ),
  });
}

export function useAuditRecord(decisionId: string | null) {
  return useQuery({
    queryKey: ["audit", "record", decisionId],
    enabled: decisionId !== null,
    queryFn: () =>
      unwrap(
        api.GET("/audit/records/{decision_id}", {
          params: { path: { decision_id: decisionId ?? "" } },
        }),
      ),
  });
}

export function usePartyStatus(address: string | null) {
  return useQuery({
    queryKey: ["compliance", address],
    enabled: address !== null,
    staleTime: 60_000,
    queryFn: () =>
      unwrap(
        api.GET("/compliance/{address}", {
          params: { path: { address: address ?? "" } },
        }),
      ),
  });
}

export function usePolicy() {
  return useQuery({
    queryKey: ["policy"],
    queryFn: () => unwrap(api.GET("/policy")),
    staleTime: Infinity, // policy changes require a server restart
  });
}

/**
 * Who the current approver token belongs to, per the server (W2). Disabled
 * without a token; a 401 is a final answer, not something to retry.
 */
export function useApproverMe(token: string) {
  return useQuery({
    queryKey: ["approvers", "me", token],
    enabled: token !== "",
    retry: false,
    staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/approvers/me")),
  });
}

export function useCannedInstructions() {
  return useQuery({
    queryKey: ["agent", "instructions"],
    queryFn: () => unwrap(api.GET("/agent/instructions")),
    staleTime: Infinity,
  });
}

// ---------------------------------------------------------------- mutations

export function useVerifyDecision() {
  return useMutation({
    mutationFn: (decisionId: string) =>
      unwrap(
        api.GET("/audit/verify/{decision_id}", {
          params: { path: { decision_id: decisionId } },
        }),
      ),
  });
}

/**
 * Seal every unanchored audit record into one Merkle batch and put the root
 * on-chain. Resolves with the batch — including the explorer url for the
 * transaction, which is the only way a third party can check the root.
 */
export function useAnchorRecords() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/anchor")),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["metrics"] });
    },
  });
}

export function useRunAgent() {
  return useMutation({
    mutationFn: (instruction: string) =>
      unwrap(api.POST("/agent/run", { body: { instruction } })),
  });
}

interface ActOnProposal {
  decisionId: string;
  comment: string;
}

/**
 * Approve/reject with optimistic removal from the pending list and rollback
 * on failure (F2). The pending row disappears immediately; if the server
 * refuses, it snaps back and the error surfaces.
 */
function useProposalAction(action: "approve" | "reject") {
  const queryClient = useQueryClient();
  return useMutation({
    // the approver is whoever the bearer token resolves to on the server;
    // the body carries the comment and nothing else (W2, AGENTS.md C4)
    mutationFn: ({ decisionId, comment }: ActOnProposal) =>
      unwrap(
        api.POST(`/proposals/{decision_id}/${action}`, {
          params: { path: { decision_id: decisionId } },
          body: { comment },
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

export function useApproveProposal() {
  return useProposalAction("approve");
}

export function useRejectProposal() {
  return useProposalAction("reject");
}
