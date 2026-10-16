import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  startAuthentication,
  startRegistration,
  type AuthenticationResponseJSON,
  type RegistrationResponseJSON,
} from "@simplewebauthn/browser";
import App from "../../App";
import { API_URL } from "../../api/client";
import { makeProposal } from "../../test/fixtures";
import { server } from "../../test/msw";
import { FakeEventSource, renderApp } from "../../test/render";

vi.mock("@simplewebauthn/browser", () => ({
  startRegistration: vi.fn(),
  startAuthentication: vi.fn(),
}));

const mockRegistration = vi.mocked(startRegistration);
const mockAuthentication = vi.mocked(startAuthentication);

const REGISTRATION_CREDENTIAL = {
  id: "cred-registration",
  rawId: "cred-registration",
  type: "public-key",
  clientExtensionResults: {},
  response: {},
} as unknown as RegistrationResponseJSON;

const ASSERTION_CREDENTIAL = {
  id: "cred-assertion",
  rawId: "cred-assertion",
  type: "public-key",
  clientExtensionResults: {},
  response: { signature: "sig" },
} as unknown as AuthenticationResponseJSON;

function guardianHandlers() {
  return [
    http.post(`${API_URL}/guardian/pair/options`, () =>
      HttpResponse.json({ challenge: "cGFpcg", rp: { id: "localhost" } }),
    ),
    http.post(`${API_URL}/guardian/pair/complete`, () =>
      HttpResponse.json({
        credential_id: "cred-registration",
        sign_count: 0,
        approver_id: "casey",
        display_name: "Casey",
      }),
    ),
    http.post(`${API_URL}/guardian/auth-options/:id`, () =>
      HttpResponse.json({ challenge: "ZGVjaXNpb24", allowCredentials: [] }),
    ),
  ];
}

function pairInStorage() {
  window.localStorage.setItem(
    "aegis.guardian",
    JSON.stringify({
      paired: true,
      credentialId: "cred-assertion",
      approverId: "casey",
      displayName: "Casey",
    }),
  );
}

describe("GuardianPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    server.use(...guardianHandlers());
  });

  it("pairs the device: code, passkey ceremony, then the queue", async () => {
    const completes: unknown[] = [];
    server.use(
      http.post(
        `${API_URL}/guardian/pair/complete`,
        async ({ request }) => {
          completes.push(await request.json());
          return HttpResponse.json({
            credential_id: "cred-registration",
            sign_count: 0,
            approver_id: "casey",
            display_name: "Casey",
          });
        },
      ),
    );
    mockRegistration.mockResolvedValue(REGISTRATION_CREDENTIAL);
    renderApp(<App />, { route: "/guardian" });
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("pairing code"), "abq7k2");
    await user.click(
      screen.getByRole("button", { name: "Pair with passkey" }),
    );

    // the queue appears once pairing lands
    expect(await screen.findByTestId("guardian-dec-1")).toBeInTheDocument();
    expect(mockRegistration).toHaveBeenCalledWith({
      optionsJSON: expect.objectContaining({ challenge: "cGFpcg" }),
    });
    expect(completes).toEqual([
      {
        code: "ABQ7K2", // uppercased by the input
        credential: expect.objectContaining({ id: "cred-registration" }),
      },
    ]);
    expect(
      JSON.parse(window.localStorage.getItem("aegis.guardian") ?? "null"),
    ).toEqual({
      paired: true,
      credentialId: "cred-registration",
      approverId: "casey",
      displayName: "Casey",
    });
    // the phone says whose passkey it now holds, as the server reported it
    expect(screen.getByTestId("guardian-identity")).toHaveTextContent(
      "signing as Casey (passkey cred-reg)",
    );
  });

  it("asks to pair again when the stored pairing predates approver binding", async () => {
    window.localStorage.setItem(
      "aegis.guardian",
      JSON.stringify({ paired: true, credentialId: "cred-old" }),
    );
    renderApp(<App />, { route: "/guardian" });
    expect(await screen.findByLabelText("pairing code")).toBeInTheDocument();
    expect(screen.queryByTestId("guardian-dec-1")).toBeNull();
  });

  it("surfaces WebAuthn registration failures with their error name", async () => {
    mockRegistration.mockRejectedValue(
      Object.assign(new Error("Registration ceremony was cancelled"), {
        name: "NotAllowedError",
      }),
    );
    renderApp(<App />, { route: "/guardian" });
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("pairing code"), "ABQ7K2");
    await user.click(
      screen.getByRole("button", { name: "Pair with passkey" }),
    );

    expect(
      await screen.findByText(
        "NotAllowedError: Registration ceremony was cancelled",
      ),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem("aegis.guardian")).toBeNull();
  });

  it("shows amount, to-address and TTL on a pending card", async () => {
    pairInStorage();
    renderApp(<App />, { route: "/guardian" });

    const card = within(await screen.findByTestId("guardian-dec-1"));
    expect(card.getByText("50,000")).toBeInTheDocument();
    expect(card.getByTitle(/^0x7099/)).toBeInTheDocument(); // to-address chip
    expect(card.getByText(/^\d+:\d{2}$/)).toBeInTheDocument(); // countdown
  });

  it("approves after Face ID and removes the card optimistically", async () => {
    const decides: unknown[] = [];
    let pending = [makeProposal()];
    server.use(
      http.get(`${API_URL}/proposals`, () => HttpResponse.json(pending)),
      http.post(
        `${API_URL}/guardian/decide/:id`,
        async ({ request, params }) => {
          decides.push(await request.json());
          pending = [];
          return HttpResponse.json({
            ...makeProposal({
              decision_id: String(params.id),
              status: "approved",
            }),
            human_presence: { credential_id: "cred-assertion", sign_count: 1 },
          });
        },
      ),
    );
    mockAuthentication.mockResolvedValue(ASSERTION_CREDENTIAL);
    pairInStorage();
    renderApp(<App />, { route: "/guardian" });
    const user = userEvent.setup();

    const card = await screen.findByTestId("guardian-dec-1");
    await user.type(
      within(card).getByLabelText("comment for dec-1"),
      "looks fine",
    );
    await user.click(within(card).getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(screen.queryByTestId("guardian-dec-1")).toBeNull(),
    );
    expect(mockAuthentication).toHaveBeenCalledWith({
      optionsJSON: expect.objectContaining({ challenge: "ZGVjaXNpb24" }),
    });
    expect(decides).toEqual([
      {
        action: "approve",
        comment: "looks fine",
        credential: expect.objectContaining({ id: "cred-assertion" }),
      },
    ]);
  });

  it("restores the card and shows the error when the decide is refused", async () => {
    server.use(
      http.post(`${API_URL}/guardian/decide/:id`, () =>
        HttpResponse.json(
          { detail: "assertion verification failed: bad challenge" },
          { status: 400 },
        ),
      ),
    );
    mockAuthentication.mockResolvedValue(ASSERTION_CREDENTIAL);
    pairInStorage();
    renderApp(<App />, { route: "/guardian" });
    const user = userEvent.setup();

    const card = await screen.findByTestId("guardian-dec-1");
    await user.click(within(card).getByRole("button", { name: "Reject" }));

    expect(
      await screen.findByText("assertion verification failed: bad challenge"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("guardian-dec-1")).toBeInTheDocument();
  });

  it("keeps the card when Face ID itself is cancelled", async () => {
    mockAuthentication.mockRejectedValue(
      Object.assign(new Error("Authentication ceremony was cancelled"), {
        name: "NotAllowedError",
      }),
    );
    pairInStorage();
    renderApp(<App />, { route: "/guardian" });
    const user = userEvent.setup();

    const card = await screen.findByTestId("guardian-dec-1");
    await user.click(within(card).getByRole("button", { name: "Approve" }));

    expect(
      await screen.findByText(
        "NotAllowedError: Authentication ceremony was cancelled",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("guardian-dec-1")).toBeInTheDocument();
  });

  it("vibrates on a new escalation event", async () => {
    const vibrate = vi.fn();
    Object.defineProperty(navigator, "vibrate", {
      value: vibrate,
      configurable: true,
      writable: true,
    });
    pairInStorage();
    renderApp(<App />, { route: "/guardian" });
    await screen.findByTestId("guardian-dec-1");

    FakeEventSource.last().emit({
      seq: 99,
      type: "proposal.created",
      data: {},
    });

    await waitFor(() => expect(vibrate).toHaveBeenCalledWith([200, 100, 200]));
  });
});
