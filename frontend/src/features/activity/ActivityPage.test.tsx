import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import App from "../../App";
import { API_URL } from "../../api/client";
import { makeDecision } from "../../test/fixtures";
import { server } from "../../test/msw";
import { FakeEventSource, renderApp } from "../../test/render";

function seedDecisions() {
  server.use(
    http.get(`${API_URL}/decisions`, () =>
      HttpResponse.json({
        items: [
          makeDecision({ decision_id: "d-allow" }),
          makeDecision({
            decision_id: "d-deny",
            effect: "deny",
            status: "denied",
            matched_rules: ["deny-frozen-party"],
            tx_hash: null,
            proposal: { operation: 2, amount: 10 },
          }),
        ],
        total: 2,
        limit: 100,
        offset: 0,
      }),
    ),
  );
}

describe("ActivityPage", () => {
  it("renders decisions with effect-colored badges and rules", async () => {
    seedDecisions();
    renderApp(<App />, { route: "/activity" });
    const feed = await screen.findByTestId("activity-feed");
    expect(within(feed).getByText("allow")).toBeInTheDocument();
    expect(within(feed).getByText("deny")).toBeInTheDocument();
    expect(
      within(feed).getByText("allow-small-compliant-transfer"),
    ).toBeInTheDocument();
  });

  it("filters by effect and by operation", async () => {
    seedDecisions();
    renderApp(<App />, { route: "/activity" });
    await screen.findByTestId("activity-feed");
    const user = userEvent.setup();

    const effectGroup = screen.getByRole("group", { name: "filter by effect" });
    await user.click(within(effectGroup).getByRole("button", { name: "deny" }));
    let feed = screen.getByTestId("activity-feed");
    expect(within(feed).queryByText("allow")).toBeNull();
    expect(within(feed).getByText("deny")).toBeInTheDocument();

    await user.click(within(effectGroup).getByRole("button", { name: "all" }));
    const opGroup = screen.getByRole("group", { name: "filter by operation" });
    await user.click(within(opGroup).getByRole("button", { name: "transfer" }));
    feed = screen.getByTestId("activity-feed");
    expect(within(feed).getByText("allow")).toBeInTheDocument();
    expect(within(feed).queryByText("deny")).toBeNull(); // mint filtered out
  });

  it("interleaves live agent.step events from the SSE stream", async () => {
    seedDecisions();
    renderApp(<App />, { route: "/activity" });
    await screen.findByTestId("activity-feed");

    FakeEventSource.last().emit({
      seq: 1,
      type: "agent.step",
      data: {
        run_id: "r1",
        instruction: "Pay the vendor invoice batch",
        phase: "awaiting_approval",
        decision_id: "d9",
      },
    });

    const feed = screen.getByTestId("activity-feed");
    expect(
      await within(feed).findByText(/awaiting_approval/),
    ).toBeInTheDocument();
    expect(
      within(feed).getByText("Pay the vendor invoice batch"),
    ).toBeInTheDocument();
  });
});
