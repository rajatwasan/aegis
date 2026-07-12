import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "./msw";

// MSW guards every test: no request ever leaves the process.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
});
afterAll(() => server.close());

// jsdom lacks EventSource; tests inject FakeEventSource via EventsProvider.
class NoopEventSource {
  close(): void {}
  addEventListener(): void {}
}
(globalThis as Record<string, unknown>).EventSource ??= NoopEventSource;
