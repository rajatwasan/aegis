import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import App from "../../App";
import { API_URL } from "../../api/client";
import {
  ANCHOR_ADDRESS,
  ANCHOR_TX,
  EXPLORER,
  makeAnchor,
  makeLocalAnchor,
  makeLocalChainStatus,
  makeMetrics,
} from "../../test/fixtures";
import { server } from "../../test/msw";
import { renderApp } from "../../test/render";

describe("DashboardPage", () => {
  it("renders the stat cards from /metrics", async () => {
    renderApp(<App />, { route: "/" });
    expect(await screen.findByText("total decisions")).toBeInTheDocument();
    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    // denials card + injections blocked from evals/report.md via /metrics
    expect(screen.getByText("denials")).toBeInTheDocument();
    expect(screen.getByText("injections blocked")).toBeInTheDocument();
    expect(screen.getByText("49")).toBeInTheDocument();
    expect(screen.getByText("0/49 bypasses in evals")).toBeInTheDocument();
  });

  it("draws the decisions-by-effect bar in the status colors", async () => {
    renderApp(<App />, { route: "/" });
    const bar = await screen.findByTestId("effect-bar");
    expect(
      within(bar).getByRole("img", { name: "allow: 8" }),
    ).toBeInTheDocument();
    expect(
      within(bar).getByRole("img", { name: "escalate: 3" }),
    ).toBeInTheDocument();
    expect(
      within(bar).getByRole("img", { name: "deny: 1" }),
    ).toBeInTheDocument();
  });

  it("shows the last anchor with a link to track its transaction on-chain", async () => {
    renderApp(<App />, { route: "/" });
    expect(await screen.findByText("batch #1")).toBeInTheDocument();
    expect(screen.getByText("8 records sealed")).toBeInTheDocument();

    const card = screen.getByTestId("anchor-card");
    expect(within(card).getByText("base-sepolia")).toBeInTheDocument();
    expect(within(card).getByText("19482331")).toBeInTheDocument();
    expect(
      within(card).getByRole("link", { name: /0xefefefef/ }),
    ).toHaveAttribute("href", `${EXPLORER}/tx/${ANCHOR_TX}`);
    expect(
      within(card).getByRole("link", { name: /AuditAnchor contract/ }),
    ).toHaveAttribute("href", `${EXPLORER}/address/${ANCHOR_ADDRESS}`);
  });

  it("anchors on demand and shows the new transaction link", async () => {
    const fresh = makeAnchor({ batch_id: 7, record_count: 3 });
    server.use(
      http.post(`${API_URL}/anchor`, () =>
        HttpResponse.json({ anchored: true, batch: fresh }),
      ),
    );
    renderApp(<App />, { route: "/" });

    await userEvent.click(
      await screen.findByRole("button", { name: "Anchor now" }),
    );

    const card = screen.getByTestId("anchor-card");
    expect(await within(card).findByText("batch #7")).toBeInTheDocument();
    expect(within(card).getByText("3 records sealed")).toBeInTheDocument();
    expect(
      within(card).getByRole("link", { name: /0xefefefef/ }),
    ).toHaveAttribute("href", `${EXPLORER}/tx/${ANCHOR_TX}`);
  });

  it("says so when there is nothing new to anchor", async () => {
    server.use(
      http.post(`${API_URL}/anchor`, () =>
        HttpResponse.json({ anchored: false, batch: makeAnchor() }),
      ),
    );
    renderApp(<App />, { route: "/" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Anchor now" }),
    );
    expect(
      await screen.findByText(/Nothing new to anchor/),
    ).toBeInTheDocument();
  });

  it("surfaces an anchoring failure instead of a silent no-op", async () => {
    server.use(
      http.post(`${API_URL}/anchor`, () =>
        HttpResponse.json(
          { detail: "no state; run the demo first" },
          { status: 503 },
        ),
      ),
    );
    renderApp(<App />, { route: "/" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Anchor now" }),
    );
    expect(
      await screen.findByText("no state; run the demo first"),
    ).toBeInTheDocument();
  });

  it("does not offer an explorer link on a local dev chain", async () => {
    server.use(
      http.get(`${API_URL}/metrics`, () =>
        HttpResponse.json(
          makeMetrics({
            chain: makeLocalChainStatus(),
            last_anchor: makeLocalAnchor(),
          }),
        ),
      ),
    );
    renderApp(<App />, { route: "/" });

    const card = await screen.findByTestId("anchor-card");
    expect(await within(card).findByText("anvil · local")).toBeInTheDocument();
    expect(within(card).getByText(/no public explorer/)).toBeInTheDocument();
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
    // the hash is still shown, just not linked
    expect(within(card).getByText(/^0xefefefef\.\.\./)).toBeInTheDocument();
  });

  it("handles the cold-start empty state", async () => {
    server.use(
      http.get(`${API_URL}/metrics`, () =>
        HttpResponse.json(
          makeMetrics({
            total_decisions: 0,
            counts_by_effect: { allow: 0, escalate: 0, deny: 0 },
            escalation_rate: 0,
            pending_count: 0,
            last_anchor: null,
            injections: null,
          }),
        ),
      ),
    );
    renderApp(<App />, { route: "/" });
    expect(await screen.findByText("No decisions yet.")).toBeInTheDocument();
    expect(screen.getByText(/Nothing anchored yet/)).toBeInTheDocument();
    expect(screen.getByText("run make evals")).toBeInTheDocument();
  });
});
