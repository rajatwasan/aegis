import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../../App";
import { API_URL } from "../../api/client";
import { makeProposal } from "../../test/fixtures";
import { server, signInAsCasey, TEST_APPROVER_TOKEN } from "../../test/msw";
import { renderApp } from "../../test/render";

function renderApprovals() {
  signInAsCasey();
  return renderApp(<App />, { route: "/approvals" });
}

/** What the server saw on an approve or reject: the credential and the body. */
interface Seen {
  auth: string | null;
  body: unknown;
}

async function seen(request: Request): Promise<Seen> {
  return {
    auth: request.headers.get("authorization"),
    body: await request.json(),
  };
}

const AS_CASEY = `Bearer ${TEST_APPROVER_TOKEN}`;

async function openDrawer() {
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("proposal-dec-1"));
  return { user, drawer: await screen.findByRole("dialog") };
}

describe("ApprovalsPage", () => {
  beforeEach(() => window.localStorage.clear());

  it("renders pending proposals newest first with route, amount and TTL", async () => {
    const now = Date.now() / 1000;
    server.use(
      http.get(`${API_URL}/proposals`, () =>
        HttpResponse.json([
          makeProposal({ decision_id: "older", created_at: now - 300 }),
          makeProposal({ decision_id: "newer", created_at: now - 10 }),
        ]),
      ),
    );
    renderApprovals();

    const rows = await screen.findAllByTestId(/^proposal-/);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "proposal-newer",
      "proposal-older",
    ]);
    const newest = within(rows[0] as HTMLElement);
    expect(newest.getByText("transfer")).toBeInTheDocument();
    expect(newest.getByText("50,000")).toBeInTheDocument();
    // both parties, middle-truncated
    expect(newest.getByTitle(/^0xf39F/)).toBeInTheDocument();
    expect(newest.getByTitle(/^0x7099/)).toBeInTheDocument();
  });

  it("shows the empty state when nothing is pending", async () => {
    server.use(http.get(`${API_URL}/proposals`, () => HttpResponse.json([])));
    renderApprovals();
    expect(
      await screen.findByText("No proposals waiting."),
    ).toBeInTheDocument();
  });

  it("counts down a live TTL and decays out an expired row", async () => {
    const now = Date.now() / 1000;
    server.use(
      http.get(`${API_URL}/proposals`, () =>
        HttpResponse.json([
          makeProposal({ decision_id: "live", expires_at: now + 95 }),
          makeProposal({ decision_id: "dead", expires_at: now - 5 }),
        ]),
      ),
    );
    renderApprovals();

    const live = await screen.findByTestId("proposal-live");
    expect(within(live).getByText(/^1:3[0-5]$/)).toBeInTheDocument();

    const dead = screen.getByTestId("proposal-dead");
    expect(within(dead).getByText("expired")).toBeInTheDocument();
    expect(dead.className).toContain("decay-out");
  });

  it("approves with a required comment and removes the row", async () => {
    const approvals: Seen[] = [];
    let pending = [makeProposal()];
    server.use(
      http.get(`${API_URL}/proposals`, () => HttpResponse.json(pending)),
      http.post(
        `${API_URL}/proposals/:id/approve`,
        async ({ request, params }) => {
          approvals.push(await seen(request));
          pending = [];
          return HttpResponse.json(
            makeProposal({
              decision_id: String(params.id),
              status: "approved",
            }),
          );
        },
      ),
    );
    renderApprovals();
    const { user, drawer } = await openDrawer();

    // policy decision panel explains WHY it escalated
    expect(
      await within(drawer).findByText("escalate-large-transfer"),
    ).toBeInTheDocument();
    expect(
      within(drawer).getByText("operation is transfer and amount > 10,000"),
    ).toBeInTheDocument();
    // both parties' standing from /compliance
    expect(await within(drawer).findAllByText("compliant")).toHaveLength(2);

    const approveButton = within(drawer).getByRole("button", {
      name: "Approve",
    });
    expect(approveButton).toBeDisabled(); // no comment yet
    await user.type(
      within(drawer).getByLabelText("comment (required)"),
      "looks legit",
    );
    await user.click(approveButton);

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // the credential rides in the header; the body is the comment only (W2)
    expect(approvals).toEqual([
      { auth: AS_CASEY, body: { comment: "looks legit" } },
    ]);
    await waitFor(() =>
      expect(screen.queryByTestId("proposal-dec-1")).toBeNull(),
    );
  });

  it("rejects with a comment", async () => {
    const rejections: Seen[] = [];
    server.use(
      http.post(
        `${API_URL}/proposals/:id/reject`,
        async ({ request, params }) => {
          rejections.push(await seen(request));
          return HttpResponse.json(
            makeProposal({
              decision_id: String(params.id),
              status: "rejected",
            }),
          );
        },
      ),
    );
    renderApprovals();
    const { user, drawer } = await openDrawer();

    await user.type(
      within(drawer).getByLabelText("comment (required)"),
      "wrong counterparty",
    );
    await user.click(within(drawer).getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(rejections).toEqual([
      { auth: AS_CASEY, body: { comment: "wrong counterparty" } },
    ]);
  });

  it("shows dual-control progress and keeps the drawer open after the first approval", async () => {
    const oneApproval = [
      {
        approver: "casey",
        display_name: "Casey",
        auth_method: "token",
        comment: "first sign-off",
        ts: Date.now() / 1000 - 30,
      },
    ];
    server.use(
      http.get(`${API_URL}/proposals`, () =>
        HttpResponse.json([makeProposal({ approvals: oneApproval })]),
      ),
      http.get(`${API_URL}/proposals/:id`, () =>
        HttpResponse.json(makeProposal({ approvals: oneApproval })),
      ),
      http.post(
        `${API_URL}/proposals/:id/approve`,
        () => HttpResponse.json(makeProposal({ approvals: oneApproval })), // still pending
      ),
    );
    renderApprovals();

    const row = await screen.findByTestId("proposal-dec-1");
    expect(within(row).getByText("1 of 2")).toBeInTheDocument();

    const { drawer } = await openDrawer();
    expect(
      within(drawer).getByText(/dual control: 1 of 2 recorded/),
    ).toBeInTheDocument();
    expect(within(drawer).getByText("first sign-off")).toBeInTheDocument();
    // the recorded approver is named by the server's identity record
    const entry = within(drawer).getByText("first sign-off").closest("li");
    expect(entry).toHaveTextContent("Casey");
    expect(entry).toHaveTextContent("token");
  });

  it("rolls the row back and surfaces the error when approval fails", async () => {
    server.use(
      http.post(`${API_URL}/proposals/:id/approve`, () =>
        HttpResponse.json(
          { detail: "proposal is expired, not pending" },
          { status: 409 },
        ),
      ),
    );
    renderApprovals();
    const { user, drawer } = await openDrawer();

    await user.type(
      within(drawer).getByLabelText("comment (required)"),
      "too late",
    );
    await user.click(within(drawer).getByRole("button", { name: "Approve" }));

    // the error surfaces in the drawer and the optimistic removal rolls back
    expect(
      await within(drawer).findByText("proposal is expired, not pending"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("proposal-dec-1")).toBeInTheDocument();
  });

  it("supports j/k row navigation and a-to-approve from the keyboard", async () => {
    const now = Date.now() / 1000;
    const approvals: Seen[] = [];
    server.use(
      http.get(`${API_URL}/proposals`, () =>
        HttpResponse.json([
          makeProposal({ decision_id: "first", created_at: now - 10 }),
          makeProposal({ decision_id: "second", created_at: now - 60 }),
        ]),
      ),
      http.post(
        `${API_URL}/proposals/:id/approve`,
        async ({ request, params }) => {
          approvals.push(await seen(request));
          return HttpResponse.json(
            makeProposal({
              decision_id: String(params.id),
              status: "approved",
            }),
          );
        },
      ),
    );
    renderApprovals();
    const user = userEvent.setup();

    const first = await screen.findByTestId("proposal-first");
    first.focus();
    await user.keyboard("j");
    expect(screen.getByTestId("proposal-second")).toHaveFocus();
    await user.keyboard("k");
    expect(first).toHaveFocus();

    await user.keyboard("a"); // opens the drawer armed to approve
    const drawer = await screen.findByRole("dialog");
    const comment = within(drawer).getByLabelText("comment (required)");
    await waitFor(() => expect(comment).toHaveFocus());
    expect(within(drawer).getByText(/enter .* to approve/)).toBeInTheDocument();

    await user.keyboard("ship it{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(approvals).toEqual([
      { auth: AS_CASEY, body: { comment: "ship it" } },
    ]);
  });

  it("requires an approver token before acting", async () => {
    renderApp(<App />, { route: "/approvals" }); // no token in storage
    const user = userEvent.setup();
    expect(screen.getByTestId("approver-status")).toHaveTextContent(
      "not signed in",
    );
    await user.click(await screen.findByTestId("proposal-dec-1"));
    const drawer = await screen.findByRole("dialog");

    expect(
      within(drawer).getByText(/paste your approver token above/),
    ).toBeInTheDocument();
    await user.type(
      within(drawer).getByLabelText("comment (required)"),
      "a comment",
    );
    expect(
      within(drawer).getByRole("button", { name: "Approve" }),
    ).toBeDisabled();
  });

  it("names the approver the server resolved from the token", async () => {
    renderApprovals();
    expect(await screen.findByText("Casey")).toBeInTheDocument();
    const { drawer } = await openDrawer();
    expect(within(drawer).getByText(/acting as/)).toHaveTextContent(
      "acting as Casey",
    );
  });

  it("says token rejected when the server does not recognize the token", async () => {
    window.localStorage.setItem("aegis.approver_token", "tok-forged");
    renderApp(<App />, { route: "/approvals" });
    expect(await screen.findByText("token rejected")).toBeInTheDocument();
    const { drawer } = await openDrawer();
    expect(
      within(drawer).getByRole("button", { name: "Approve" }),
    ).toBeDisabled();
  });

  it("surfaces a 401 on approve as a rejected token and restores the row", async () => {
    // the token resolved when the page loaded, then was revoked server side
    server.use(
      http.post(`${API_URL}/proposals/:id/approve`, () =>
        HttpResponse.json(
          { detail: "approver token not recognized" },
          { status: 401 },
        ),
      ),
    );
    renderApprovals();
    const { user, drawer } = await openDrawer();
    await user.type(
      within(drawer).getByLabelText("comment (required)"),
      "late approval",
    );
    await user.click(within(drawer).getByRole("button", { name: "Approve" }));

    expect(
      await within(drawer).findByText(
        "token rejected: approver token not recognized",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("proposal-dec-1")).toBeInTheDocument();
  });
});

describe("PolicyPage", () => {
  it("renders the rule table with hash and yaml", async () => {
    renderApp(<App />, { route: "/policy" });
    expect(await screen.findByText("deny-frozen-party")).toBeInTheDocument();
    expect(screen.getByText("a party is frozen")).toBeInTheDocument();
    expect(screen.getByText(/version: 1/)).toBeInTheDocument();
    expect(
      screen.getByText(/version 1 — first match wins, default escalate/),
    ).toBeInTheDocument();
  });
});
