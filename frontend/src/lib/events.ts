/**
 * SSE plumbing: one EventSource per app, fanned out to subscribers.
 *
 * The backend emits data-only SSE frames whose payload is
 * `{ seq, type, ts, data }`. EventSource reconnects natively; we track
 * connection status for the status bar and keep a pure reducer over the
 * event history for the activity feed.
 */

export type BusEventType =
  | "proposal.created"
  | "proposal.approved"
  | "proposal.rejected"
  | "proposal.expired"
  | "decision.recorded"
  | "anchor.created"
  | "agent.step";

export interface BusEvent {
  seq: number;
  type: BusEventType;
  ts: string;
  data: Record<string, unknown>;
}

export type ConnectionStatus = "connecting" | "open" | "reconnecting";

type EventListener = (event: BusEvent) => void;
type StatusListener = (status: ConnectionStatus) => void;

/** Minimal EventSource surface so tests can inject a fake. */
export interface EventSourceLike {
  close(): void;
  addEventListener(
    type: string,
    listener: (event: MessageEvent<string>) => void,
  ): void;
}
export type EventSourceFactory = (url: string) => EventSourceLike;

export function parseBusEvent(raw: string): BusEvent | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" &&
      value !== null &&
      "seq" in value &&
      "type" in value &&
      "data" in value
    ) {
      return value as BusEvent;
    }
    return null;
  } catch {
    return null;
  }
}

export class EventStream {
  private source: EventSourceLike | null = null;
  private listeners = new Set<EventListener>();
  private statusListeners = new Set<StatusListener>();
  status: ConnectionStatus = "connecting";

  constructor(
    private readonly url: string,
    private readonly factory: EventSourceFactory = (u) => new EventSource(u),
  ) {}

  start(): void {
    if (this.source !== null) return;
    const source = this.factory(this.url);
    source.addEventListener("open", () => this.setStatus("open"));
    source.addEventListener("error", () => this.setStatus("reconnecting"));
    source.addEventListener("message", (raw) => {
      const event = parseBusEvent(raw.data);
      if (event !== null) {
        for (const listener of this.listeners) listener(event);
      }
    });
    this.source = source;
  }

  stop(): void {
    this.source?.close();
    this.source = null;
  }

  subscribe(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  subscribeStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  private setStatus(status: ConnectionStatus): void {
    if (this.status === status) return;
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }
}

/**
 * Which query keys go stale when an event arrives. The SSE stream is the
 * only invalidation trigger the app needs — no polling.
 */
export function invalidationsFor(type: BusEventType): string[][] {
  switch (type) {
    case "proposal.created":
    case "proposal.approved":
    case "proposal.rejected":
    case "proposal.expired":
      return [["proposals"], ["metrics"]];
    case "decision.recorded":
      return [["decisions"], ["audit"], ["metrics"]];
    case "anchor.created":
      return [["audit"], ["metrics"]];
    case "agent.step":
      return [];
  }
}

// ---------------------------------------------------------------- feed store

export interface FeedState {
  events: BusEvent[]; // newest first
  lastSeq: number;
  paused: boolean;
}

export const emptyFeed: FeedState = { events: [], lastSeq: 0, paused: false };

export const FEED_CAP = 500;

/** Pure reducer over incoming bus events (unit-tested in F3). */
export function feedReducer(
  state: FeedState,
  event: BusEvent,
  cap: number = FEED_CAP,
): FeedState {
  if (event.seq <= state.lastSeq && state.lastSeq !== 0) return state; // replays
  const events = [event, ...state.events];
  if (events.length > cap) events.length = cap;
  return { ...state, events, lastSeq: event.seq };
}
