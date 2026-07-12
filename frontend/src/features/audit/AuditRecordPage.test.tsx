import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import App from "../../App";
import { API_URL } from "../../api/client";
import { makeVerifyResponse } from "../../test/fixtures";
import { server } from "../../test/msw";
import { renderApp } from "../../test/render";

describe("AuditPage", () => {
  it("lists records newest first with pagination info", async () => {
    renderApp(<App />, { route: "/audit" });
    expect(
      await screen.findByText("3 records, hash-chained and Ed25519-signed"),
    ).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: /^rec-/ });
    expect(links.map((l) => l.textContent)).toEqual([
      "rec-2…",
      "rec-1…",
      "rec-0…",
    ]);
    expect(screen.getByText("1–3 of 3")).toBeInTheDocument();
  });
});

describe("AuditRecordPage", () => {
  it("shows the chain neighborhood with linked prev_hash markers", async () => {
    renderApp(<App />, { route: "/audit/rec-1" });
    const chain = await screen.findByTestId("chain-view");
    // three neighbors, two links, both verified locally (prev matches hash)
    expect(within(chain).getAllByRole("link")).toHaveLength(3);
    expect(within(chain).getAllByText("links")).toHaveLength(2);
    // canonical JSON + integrity fields render
    expect(screen.getByText(/"decision_id": "rec-1"/)).toBeInTheDocument();
    expect(screen.getByText("signature (Ed25519)")).toBeInTheDocument();
  });

  it("renders PROOF OK with the merkle path and matching roots", async () => {
    renderApp(<App />, { route: "/audit/rec-1" });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Verify against chain" }),
    );

    const panel = await screen.findByTestId("verify-panel");
    expect(within(panel).getByText("PROOF OK")).toBeInTheDocument();
    expect(within(panel).getByText("anchor batch #0")).toBeInTheDocument();
    expect(within(panel).getByText("level 0")).toBeInTheDocument();
    expect(within(panel).getByText("level 1")).toBeInTheDocument();
    expect(within(panel).getByText("roots match")).toBeInTheDocument();
  });

  it("renders PROOF FAIL with the reason", async () => {
    server.use(
      http.get(`${API_URL}/audit/verify/:id`, () =>
        HttpResponse.json(
          makeVerifyResponse({
            PROOF_OK: false,
            reason: "record 1 tampered (hash mismatch)",
            onchain_root: "44".repeat(32),
          }),
        ),
      ),
    );
    renderApp(<App />, { route: "/audit/rec-1" });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Verify against chain" }),
    );

    const panel = await screen.findByTestId("verify-panel");
    expect(within(panel).getByText("PROOF FAIL")).toBeInTheDocument();
    expect(
      within(panel).getByText("record 1 tampered (hash mismatch)"),
    ).toBeInTheDocument();
    expect(within(panel).getByText("mismatch")).toBeInTheDocument();
  });

  it("shows the error state for an unknown record", async () => {
    server.use(
      http.get(`${API_URL}/audit/records/:id`, () =>
        HttpResponse.json({ detail: "unknown audit record" }, { status: 404 }),
      ),
    );
    renderApp(<App />, { route: "/audit/nope" });
    expect(await screen.findByText("unknown audit record")).toBeInTheDocument();
  });
});
