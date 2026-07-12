import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import App from "../../App";
import { API_URL } from "../../api/client";
import { makeMetrics } from "../../test/fixtures";
import { server } from "../../test/msw";
import { FakeEventSource, renderApp } from "../../test/render";

describe("Shell", () => {
  it("renders the left nav with all five sections plus dashboard", () => {
    renderApp(<App />);
    const nav = screen.getByRole("navigation", { name: "primary" });
    for (const label of [
      "Dashboard",
      "Approvals",
      "Activity",
      "Audit",
      "Policy",
      "Console",
    ]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("shows chain connection, last anchor, and pending count from /metrics", async () => {
    renderApp(<App />);
    expect(await screen.findByText("chain 31337")).toBeInTheDocument();
    expect(await screen.findByTestId("pending-count")).toHaveTextContent("2");
    // last anchor root truncates middle in mono
    expect(screen.getByText(/0xcdcd.*cdcd/)).toBeInTheDocument();
  });

  it("shows disconnected state when the chain is not configured", async () => {
    server.use(
      http.get(`${API_URL}/metrics`, () =>
        HttpResponse.json(
          makeMetrics({
            chain: {
              configured: false,
              connected: false,
              rpc_url: null,
              chain_id: null,
            },
            last_anchor: null,
            pending_count: 0,
          }),
        ),
      ),
    );
    renderApp(<App />);
    expect(await screen.findByText("chain not configured")).toBeInTheDocument();
    expect(screen.getByText("none")).toBeInTheDocument();
  });

  it("tracks the SSE connection state in the status bar", async () => {
    renderApp(<App />);
    const stream = screen.getByTestId("stream-status");
    expect(stream).toHaveTextContent("connecting");
    FakeEventSource.last().open();
    expect(await within(stream).findByText("live")).toBeInTheDocument();
    FakeEventSource.last().fail();
    expect(await within(stream).findByText("reconnecting")).toBeInTheDocument();
  });

  it("invalidates the metrics query when a proposal event arrives", async () => {
    const { queryClient } = renderApp(<App />);
    await screen.findByTestId("pending-count");

    let pendingAfter = 5;
    server.use(
      http.get(`${API_URL}/metrics`, () =>
        HttpResponse.json(makeMetrics({ pending_count: pendingAfter++ })),
      ),
    );
    FakeEventSource.last().emit({
      seq: 1,
      type: "proposal.created",
      data: { decision_id: "d1" },
    });
    await queryClient
      .getQueryCache()
      .find({ queryKey: ["metrics"] })
      ?.promise?.catch(() => undefined);
    expect(await screen.findByText("5")).toBeInTheDocument();
  });
});
