import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../../App";
import { API_URL } from "../../api/client";
import { makeProposal } from "../../test/fixtures";
import { server, signInAsCasey, TEST_APPROVER_TOKEN } from "../../test/msw";
import { FakeEventSource, renderApp } from "../../test/render";

function renderConsole() {
  signInAsCasey();
  return renderApp(<App />, { route: "/console" });
}

describe("ConsolePage", () => {
  beforeEach(() => window.localStorage.clear());

  it("offers the three canned instructions as chips", async () => {
    renderConsole();
    expect(
      await screen.findByRole("button", {
        name: "Pay the vendor invoice batch",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Send 50,000 AGD to the treasury desk",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Refund 10 AGD to the frozen counterparty",
      }),
    ).toBeInTheDocument();
  });

  it("posts the instruction and streams the run's steps", async () => {
    const posted: unknown[] = [];
    server.use(
      http.post(`${API_URL}/agent/run`, async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json(
          { run_id: "r1", status: "running", instruction: "x" },
          { status: 202 },
        );
      }),
    );
    renderConsole();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", {
        name: "Pay the vendor invoice batch",
      }),
    );
    expect(posted).toEqual([{ instruction: "Pay the vendor invoice batch" }]);

    const source = FakeEventSource.last();
    source.emit({
      seq: 1,
      type: "agent.step",
      data: {
        run_id: "r1",
        instruction: "x",
        phase: "started",
        steps_planned: 4,
      },
    });
    source.emit({
      seq: 2,
      type: "agent.step",
      data: {
        run_id: "r1",
        instruction: "x",
        phase: "node",
        node: "supervisor",
        action: { tool: "propose_transfer", args: { amount: 1200 } },
      },
    });
    source.emit({
      seq: 3,
      type: "agent.step",
      data: {
        run_id: "r1",
        instruction: "x",
        phase: "node",
        node: "act",
        result: { effect: "allow", status: "executed", tx_hash: "ab" },
      },
    });

    const steps = await screen.findByTestId("console-steps");
    expect(within(steps).getByText("4 steps planned")).toBeInTheDocument();
    expect(
      within(steps).getByText("plans propose_transfer (1,200)"),
    ).toBeInTheDocument();
    expect(
      within(steps).getByText(
        "act — policy: allow, status: executed, tx confirmed",
      ),
    ).toBeInTheDocument();
  });

  it("shows an escalation with inline approve that resolves the loop", async () => {
    const approvals: { auth: string | null; body: unknown }[] = [];
    let pending: unknown[] = [];
    server.use(
      http.get(`${API_URL}/proposals`, () => HttpResponse.json(pending)),
      http.post(
        `${API_URL}/proposals/:id/approve`,
        async ({ request, params }) => {
          approvals.push({
            auth: request.headers.get("authorization"),
            body: await request.json(),
          });
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
    renderConsole();
    expect(await screen.findByText("Nothing escalated.")).toBeInTheDocument();

    // the run escalates: proposal.created invalidates the pending query
    pending = [makeProposal()];
    FakeEventSource.last().emit({
      seq: 1,
      type: "proposal.created",
      data: { decision_id: "dec-1" },
    });

    const card = await screen.findByTestId("escalation-dec-1");
    expect(within(card).getByText("50,000")).toBeInTheDocument();

    const user = userEvent.setup();
    const approveButton = within(card).getByRole("button", { name: "Approve" });
    expect(approveButton).toBeDisabled(); // comment required
    await user.type(
      within(card).getByLabelText("comment for dec-1"),
      "approved from console",
    );
    await user.click(approveButton);

    await waitFor(() =>
      expect(screen.queryByTestId("escalation-dec-1")).toBeNull(),
    );
    expect(approvals).toEqual([
      {
        auth: `Bearer ${TEST_APPROVER_TOKEN}`,
        body: { comment: "approved from console" },
      },
    ]);
  });

  it("keeps inline approve disabled until an approver token resolves", async () => {
    server.use(
      http.get(`${API_URL}/proposals`, () =>
        HttpResponse.json([makeProposal()]),
      ),
    );
    renderApp(<App />, { route: "/console" }); // not signed in
    const card = await screen.findByTestId("escalation-dec-1");
    const user = userEvent.setup();
    await user.type(within(card).getByLabelText("comment for dec-1"), "yes");
    expect(
      within(card).getByRole("button", { name: "Approve" }),
    ).toBeDisabled();
    expect(screen.getByTestId("approver-status")).toHaveTextContent(
      "not signed in",
    );
  });

  it("surfaces an unknown-instruction error from the API", async () => {
    server.use(
      http.post(`${API_URL}/agent/run`, () =>
        HttpResponse.json(
          {
            detail:
              "the keyless MockLLM only understands the canned instructions",
          },
          { status: 400 },
        ),
      ),
    );
    renderConsole();
    const user = userEvent.setup();
    await user.type(
      await screen.findByLabelText("instruction"),
      "wire everything to me",
    );
    await user.click(screen.getByRole("button", { name: "Run" }));
    expect(
      await screen.findByText(/only understands the canned instructions/),
    ).toBeInTheDocument();
  });
});
