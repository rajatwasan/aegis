import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import App from "../../App";
import { API_URL } from "../../api/client";
import { makeMetrics } from "../../test/fixtures";
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
    expect(within(bar).getByRole("img", { name: "allow: 8" })).toBeInTheDocument();
    expect(
      within(bar).getByRole("img", { name: "escalate: 3" }),
    ).toBeInTheDocument();
    expect(within(bar).getByRole("img", { name: "deny: 1" })).toBeInTheDocument();
  });

  it("shows the last anchor with its transaction", async () => {
    renderApp(<App />, { route: "/" });
    expect(await screen.findByText("batch #1")).toBeInTheDocument();
    expect(screen.getByText("8 records sealed")).toBeInTheDocument();
    expect(screen.getByTitle(`0x${"ef".repeat(32)}`)).toBeInTheDocument();
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
