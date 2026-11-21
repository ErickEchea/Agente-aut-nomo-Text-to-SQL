/**
 * Workspace session: the current conversation (its turns) and one live event stream per run.
 * Lives above the routes so leaving the workspace and coming back keeps the conversation.
 */
import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";

import * as endpoints from "../../api/endpoints";
import { parseRunEvent, TERMINAL_EVENT, type RunEvent } from "../../api/events";
import { useApi } from "../../app/auth";
import { streamEvents } from "../../lib/sse";

export interface Turn {
  runId: string;
  question: string;
}

export interface RunStream {
  events: RunEvent[];
  streaming: boolean;
  finished: boolean;
  error: unknown;
}

type Action =
  | { type: "start"; runId: string }
  | { type: "event"; runId: string; event: RunEvent }
  | { type: "end"; runId: string }
  | { type: "error"; runId: string; error: unknown };

const EMPTY: RunStream = { events: [], streaming: false, finished: false, error: null };

function reducer(state: Record<string, RunStream>, action: Action): Record<string, RunStream> {
  const current = state[action.runId] ?? EMPTY;
  switch (action.type) {
    case "start":
      // The server replays every event from the start, so a restarted stream begins empty.
      return { ...state, [action.runId]: { events: [], streaming: true, finished: false, error: null } };
    case "event": {
      const last = current.events.at(-1);
      if (last && action.event.seq <= last.seq) return state;
      return {
        ...state,
        [action.runId]: {
          ...current,
          events: [...current.events, action.event],
          finished: current.finished || action.event.type === TERMINAL_EVENT,
        },
      };
    }
    case "end":
      return { ...state, [action.runId]: { ...current, streaming: false } };
    case "error":
      return { ...state, [action.runId]: { ...current, streaming: false, error: action.error } };
  }
}

interface WorkspaceValue {
  conversationId: string | null;
  turns: Turn[];
  selectedRunId: string | null;
  streams: Record<string, RunStream>;
  busy: boolean;
  ask: (question: string) => Promise<void>;
  cancel: (runId: string) => Promise<void>;
  select: (runId: string) => void;
  newConversation: () => void;
  openRun: (runId: string, conversationId: string, question: string) => void;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [streams, dispatch] = useReducer(reducer, {});
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const controllers = useRef(new Map<string, AbortController>());

  const watch = useCallback(
    (runId: string) => {
      if (controllers.current.has(runId)) return;
      const controller = new AbortController();
      controllers.current.set(runId, controller);
      dispatch({ type: "start", runId });
      streamEvents({
        url: `/api/runs/${encodeURIComponent(runId)}/events`,
        headers: api.authHeaders,
        signal: controller.signal,
        onUnauthorized: api.reauthenticate,
        onMessage: (message) => {
          const event = parseRunEvent(message.event, message.data, Number(message.id ?? 0));
          if (event) dispatch({ type: "event", runId, event });
        },
        isTerminal: (message) => message.event === TERMINAL_EVENT,
      })
        .then(() => {
          dispatch({ type: "end", runId });
          void queryClient.invalidateQueries({ queryKey: ["run", runId] });
          void queryClient.invalidateQueries({ queryKey: ["runs"] });
          void queryClient.invalidateQueries({ queryKey: ["frequent"] });
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted) dispatch({ type: "error", runId, error });
        });
    },
    [api, queryClient],
  );

  // Every turn of the conversation is streamed (finished runs replay instantly from the server).
  useEffect(() => {
    for (const turn of turns) watch(turn.runId);
  }, [turns, watch]);

  useEffect(() => {
    const active = controllers.current;
    return () => {
      for (const controller of active.values()) controller.abort();
      active.clear();
    };
  }, []);

  const busy = turns.some((turn) => {
    const stream = streams[turn.runId];
    return stream !== undefined && !stream.finished && stream.error === null;
  });

  const ask = useCallback(
    async (question: string) => {
      const created = await endpoints.startRun(api, question, conversationId);
      setConversationId(created.conversation_id);
      setTurns((previous) => [...previous, { runId: created.run_id, question }]);
      setSelectedRunId(created.run_id);
    },
    [api, conversationId],
  );

  const cancel = useCallback(
    async (runId: string) => {
      await endpoints.cancelRun(api, runId);
    },
    [api],
  );

  const newConversation = useCallback(() => {
    setTurns([]);
    setConversationId(null);
    setSelectedRunId(null);
  }, []);

  const openRun = useCallback((runId: string, conversation: string, question: string) => {
    setConversationId(conversation);
    setTurns([{ runId, question }]);
    setSelectedRunId(runId);
  }, []);

  const value = useMemo(
    () => ({
      conversationId,
      turns,
      selectedRunId,
      streams,
      busy,
      ask,
      cancel,
      select: setSelectedRunId,
      newConversation,
      openRun,
    }),
    [conversationId, turns, selectedRunId, streams, busy, ask, cancel, newConversation, openRun],
  );
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return value;
}

export function useRunStream(runId: string | null): RunStream {
  const { streams } = useWorkspace();
  return (runId ? streams[runId] : undefined) ?? EMPTY;
}
