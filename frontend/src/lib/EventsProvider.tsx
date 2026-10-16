/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_URL } from "../api/client";
import {
  EventStream,
  emptyFeed,
  feedReducer,
  invalidationsFor,
  type BusEvent,
  type ConnectionStatus,
  type EventSourceFactory,
  type FeedState,
} from "./events";

/** Ring-buffered event history behind useSyncExternalStore. */
class FeedStore {
  private state: FeedState = emptyFeed;
  private listeners = new Set<() => void>();

  push(event: BusEvent): void {
    const next = feedReducer(this.state, event);
    if (next === this.state) return;
    this.state = next;
    for (const listener of this.listeners) listener();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): FeedState => this.state;
}

interface EventsContextValue {
  stream: EventStream;
  feed: FeedStore;
  status: ConnectionStatus;
}

const EventsContext = createContext<EventsContextValue | null>(null);

export function EventsProvider({
  children,
  factory,
}: {
  children: ReactNode;
  factory?: EventSourceFactory;
}) {
  const queryClient = useQueryClient();
  const [stream] = useState(
    () => new EventStream(`${API_URL}/events`, factory),
  );
  const [feed] = useState(() => new FeedStore());
  const [status, setStatus] = useState<ConnectionStatus>(stream.status);

  useEffect(() => {
    const offEvent = stream.subscribe((event) => {
      feed.push(event);
      for (const queryKey of invalidationsFor(event.type)) {
        void queryClient.invalidateQueries({ queryKey });
      }
    });
    const offStatus = stream.subscribeStatus(setStatus);
    stream.start();
    return () => {
      offEvent();
      offStatus();
      stream.stop();
    };
  }, [stream, feed, queryClient]);

  return (
    <EventsContext.Provider value={{ stream, feed, status }}>
      {children}
    </EventsContext.Provider>
  );
}

function useEventsContext(): EventsContextValue {
  const value = useContext(EventsContext);
  if (value === null) {
    throw new Error("useEvents* hooks require an <EventsProvider>");
  }
  return value;
}

export function useConnectionStatus(): ConnectionStatus {
  return useEventsContext().status;
}

export function useFeed(): FeedState {
  const { feed } = useEventsContext();
  return useSyncExternalStore(feed.subscribe, feed.getSnapshot);
}

/** Subscribe to raw bus events (the console's live agent.step view). */
export function useBusSubscription(listener: (event: BusEvent) => void): void {
  const { stream } = useEventsContext();
  useEffect(() => stream.subscribe(listener), [stream, listener]);
}
