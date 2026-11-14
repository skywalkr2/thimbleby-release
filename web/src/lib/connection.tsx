// Whether the app can reach its server (design 7.12, "States"), told to every screen from the one place that knows: the event
// stream and the browser's own online state (`useLive`). A screen never asks the network itself; it reads this, so the offline
// banner and the lists agree, and both go away the moment the connection is back.
import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { LiveState } from "./live";
import { useRestart } from "./restart";

export interface Connection {
  /** The app cannot reach its server now. */
  offline: boolean;
  /** When the app last heard from its server: what a screen shows was loaded no later than this. */
  since: Date | null;
  /** Looks for the server at once instead of waiting for the next try. */
  retry: () => void;
}

const Context = createContext<Connection>({ offline: false, since: null, retry: () => undefined });

export function ConnectionProvider(props: { live: { state: LiveState; lastUpdate: Date | null; reconnect?: () => void; refresh: () => void }; children: ReactNode }) {
  const { state, lastUpdate, reconnect, refresh } = props.live;
  // The connection a restart the person chose dropped is the restart, which says so itself: it is not shown as offline.
  const restart = useRestart();
  const restarting = restart.phase === "waiting" || restart.busy || (restart.phase === "done" && state !== "live");
  const value = useMemo<Connection>(
    () => ({
      offline: state === "offline" && !restarting,
      since: lastUpdate,
      retry: () => {
        reconnect?.();
        refresh();
      },
    }),
    [state, lastUpdate, reconnect, refresh, restarting],
  );
  return <Context.Provider value={value}>{props.children}</Context.Provider>;
}

export function useConnection(): Connection {
  return useContext(Context);
}
