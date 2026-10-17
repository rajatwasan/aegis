/** MSW request handlers: the default happy-path API every test starts from. */

import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { API_URL } from "../api/client";
import {
  makeAuditRecord,
  makeMetrics,
  makePolicy,
  makeProposal,
  makeVerifyResponse,
} from "./fixtures";

/** The token the test approver "casey" holds; see fixtures. */
export const CASEY_TOKEN = "casey-token-0123456789abcdef0123456789";

/**
 * The real service answers 401 without a valid bearer token (AGENTS.md R4);
 * every write handler in the suite enforces the same so a regression that
 * drops the header fails here, not in production.
 */
export function requireBearer(
  request: Request,
): HttpResponse<{ detail: string }> | null {
  const header = request.headers.get("authorization");
  if (header !== `Bearer ${CASEY_TOKEN}`) {
    return HttpResponse.json(
      { detail: "approver token not recognised" },
      { status: 401, headers: { "WWW-Authenticate": "Bearer" } },
    );
  }
  return null;
}

export const handlers = [
  http.get(`${API_URL}/metrics`, () => HttpResponse.json(makeMetrics())),
  http.get(`${API_URL}/proposals`, () => HttpResponse.json([makeProposal()])),
  http.get(`${API_URL}/proposals/:id`, ({ params }) =>
    HttpResponse.json(makeProposal({ decision_id: String(params.id) })),
  ),
  http.post(`${API_URL}/proposals/:id/approve`, ({ request, params }) =>
    requireBearer(request) ??
    HttpResponse.json(
      makeProposal({ decision_id: String(params.id), status: "approved" }),
    ),
  ),
  http.post(`${API_URL}/proposals/:id/reject`, ({ request, params }) =>
    requireBearer(request) ??
    HttpResponse.json(
      makeProposal({ decision_id: String(params.id), status: "rejected" }),
    ),
  ),
  http.get(`${API_URL}/decisions`, () =>
    HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
  ),
  http.get(`${API_URL}/audit/records`, () =>
    HttpResponse.json({
      items: [makeAuditRecord(2), makeAuditRecord(1), makeAuditRecord(0)],
      total: 3,
      limit: 50,
      offset: 0,
    }),
  ),
  http.get(`${API_URL}/audit/records/:id`, ({ params }) => {
    const record = makeAuditRecord(1, { decision_id: String(params.id) });
    return HttpResponse.json({
      record,
      total: 3,
      neighbors: [makeAuditRecord(0), record, makeAuditRecord(2)],
    });
  }),
  http.get(`${API_URL}/audit/verify/:id`, ({ params }) =>
    HttpResponse.json(makeVerifyResponse({ decision_id: String(params.id) })),
  ),
  http.get(`${API_URL}/policy`, () => HttpResponse.json(makePolicy())),
  http.get(`${API_URL}/compliance/:address`, ({ params }) =>
    HttpResponse.json({
      address: String(params.address),
      known: true,
      compliant: true,
      frozen: false,
    }),
  ),
  http.get(`${API_URL}/agent/instructions`, () =>
    HttpResponse.json({
      instructions: [
        {
          instruction: "Pay the vendor invoice batch",
          description: "Three small compliant transfers",
        },
        {
          instruction: "Send 50,000 AGD to the treasury desk",
          description: "A large transfer that escalates",
        },
        {
          instruction: "Refund 10 AGD to the frozen counterparty",
          description: "A denied transfer",
        },
      ],
    }),
  ),
  http.post(`${API_URL}/agent/run`, () =>
    HttpResponse.json(
      { run_id: "run-1", status: "running", instruction: "x" },
      { status: 202 },
    ),
  ),
];

export const server = setupServer(...handlers);
