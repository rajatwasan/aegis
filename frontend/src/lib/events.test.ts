import { describe, expect, it } from "vitest";
import {
  emptyFeed,
  feedReducer,
  invalidationsFor,
  parseBusEvent,
  type BusEvent,
} from "./events";

function event(seq: number, type: BusEvent["type"] = "agent.step"): BusEvent {
  return {
    seq,
    type,
    ts: `2026-07-12T10:00:${String(seq).padStart(2, "0")}Z`,
    data: {},
  };
}

describe("feedReducer", () => {
  it("prepends events newest first and tracks lastSeq", () => {
    let state = feedReducer(emptyFeed, event(1));
    state = feedReducer(state, event(2));
    expect(state.events.map((e) => e.seq)).toEqual([2, 1]);
    expect(state.lastSeq).toBe(2);
  });

  it("drops replayed events (SSE reconnect resends)", () => {
    let state = feedReducer(emptyFeed, event(1));
    state = feedReducer(state, event(2));
    const replayed = feedReducer(state, event(2));
    expect(replayed).toBe(state); // same reference: no re-render
  });

  it("caps the ring buffer", () => {
    let state = emptyFeed;
    for (let seq = 1; seq <= 10; seq++)
      state = feedReducer(state, event(seq), 5);
    expect(state.events).toHaveLength(5);
    expect(state.events[0]?.seq).toBe(10);
    expect(state.events.at(-1)?.seq).toBe(6);
  });
});

describe("parseBusEvent", () => {
  it("accepts well-formed frames and rejects junk", () => {
    const frame = JSON.stringify(event(7, "decision.recorded"));
    expect(parseBusEvent(frame)?.seq).toBe(7);
    expect(parseBusEvent("not json")).toBeNull();
    expect(parseBusEvent('{"unrelated": true}')).toBeNull();
  });
});

describe("invalidationsFor", () => {
  it("maps proposal events to proposals+metrics and steps to nothing", () => {
    expect(invalidationsFor("proposal.approved")).toEqual([
      ["proposals"],
      ["metrics"],
    ]);
    expect(invalidationsFor("decision.recorded")).toContainEqual(["decisions"]);
    expect(invalidationsFor("agent.step")).toEqual([]);
  });
});
