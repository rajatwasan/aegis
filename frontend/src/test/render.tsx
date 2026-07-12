/** Render helpers wiring the full provider stack around a component. */

import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";
import { EventsProvider } from "../lib/EventsProvider";
import type { BusEvent, EventSourceLike } from "../lib/events";

type Listener = (event: MessageEvent<string>) => void;

/** A hand-cranked EventSource: tests push bus events with `emit`. */
export class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];
  private listeners = new Map<string, Listener[]>();
  closed = false;

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  static reset(): void {
    FakeEventSource.instances = [];
  }

  static last(): FakeEventSource {
    const instance = FakeEventSource.instances.at(-1);
    if (instance === undefined) throw new Error("no FakeEventSource created");
    return instance;
  }

  addEventListener(type: string, listener: Listener): void {
    const list = this.listeners.get(type) ?? [];
    this.listeners.set(type, [...list, listener]);
  }

  close(): void {
    this.closed = true;
  }

  open(): void {
    this.dispatch("open", "");
  }

  emit(event: Omit<BusEvent, "ts"> & { ts?: string }): void {
    const full: BusEvent = { ts: new Date().toISOString(), ...event };
    this.dispatch("message", JSON.stringify(full));
  }

  fail(): void {
    this.dispatch("error", "");
  }

  private dispatch(type: string, data: string): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data } as MessageEvent<string>);
    }
  }
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

export function renderApp(
  ui: ReactElement,
  {
    route = "/",
    queryClient = makeQueryClient(),
  }: { route?: string; queryClient?: QueryClient } = {},
) {
  FakeEventSource.reset();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <EventsProvider factory={(url) => new FakeEventSource(url)}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </EventsProvider>
    </QueryClientProvider>
  );
  return { ...render(ui, { wrapper }), queryClient };
}
