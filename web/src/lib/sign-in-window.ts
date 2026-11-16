// Signing in from setup without leaving the app: the service's page opens in its own window or tab, and this screen
// stays put, shows that it is waiting and then what happened. The window the service sends the person back to (see
// lib/sign-in-return.ts) announces how it went; a window closed with no answer is checked against the sign-in's status.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { inAppWindow, openInBrowser } from "./external-links";
import { problemText } from "./problem";
import { useWords } from "./wording";

export interface SignInAnnounced {
  outcome: string;
  name: string | null;
  error: string;
  detail: string;
  /** For a sign-in that came back as another account: the address it came back as, and the one it was meant for. */
  address?: string;
  expected?: string;
  /** For a sign-in to an account that was already signed in: its address. Its tokens were replaced, nothing was added. */
  again?: string;
}

const CHANNEL = "cockpit.sign-in";
const EVENT = "cockpit:sign-in";

/** Tells every window of the app how a sign-in went. */
export function announceSignIn(message: SignInAnnounced): void {
  window.dispatchEvent(new CustomEvent(EVENT, { detail: message }));
  try {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(CHANNEL);
    channel.postMessage(message);
    channel.close();
  } catch {
    // Without it the waiting screen finds out when the window closes.
  }
}

function listen(onMessage: (m: SignInAnnounced) => void): () => void {
  const onEvent = (e: Event) => onMessage((e as CustomEvent<SignInAnnounced>).detail);
  window.addEventListener(EVENT, onEvent);
  let channel: BroadcastChannel | undefined;
  try {
    if (typeof BroadcastChannel !== "undefined") {
      channel = new BroadcastChannel(CHANNEL);
      channel.onmessage = (e: MessageEvent<SignInAnnounced>) => onMessage(e.data);
    }
  } catch {
    channel = undefined;
  }
  return () => {
    window.removeEventListener(EVENT, onEvent);
    channel?.close();
  };
}

/** What a refused sign-in says: the service's standard error code decides the words (never its own text); a code that means an
 * administrator has to approve first says so plainly. Any other code is shown as given, with the service's reason. */
export function refusedWords(error: string, detail: string, t: (key: string, values?: Record<string, string | number>) => string): string {
  if (error === "consent_required" || error === "interaction_required" || error === "admin_consent_required") return t("sign_in.return.admin_approval");
  if (!error) return t("sign_in.return.refused");
  return detail ? t("sign_in.return.refused_detail", { error, detail }) : t("sign_in.return.refused_error", { error });
}

export type SignInPhase = "idle" | "starting" | "waiting" | "done" | "refused" | "different" | "closed" | "blocked" | "failed";

const WATCH_MS = 1000;

export function useSignInWindow(name: string): {
  /** Opens the service's page. With `account` (an address) the sign-in is for that account: another one is refused. */
  start: (account?: string) => Promise<void>;
  /** Stops waiting: the window is closed if it is still open and the screen goes back to where it was, with nothing signed in. */
  cancel: () => void;
  phase: SignInPhase;
  text: string;
  /** The window is opening or open: the button waits. */
  busy: boolean;
  /** What to show as a problem: the refusal, the closed window, the failure. */
  problem: string;
  /** After a sign-in to an account that was already signed in: "Already signed in as …; refreshed." Empty otherwise. */
  refreshed: string;
  /** The service's page opened in the person's own browser (the installed app's window), not in a window of this app. */
  away: boolean;
} {
  const { t } = useWords();
  const [phase, setPhase] = useState<SignInPhase>("idle");
  const [text, setText] = useState("");
  const [refreshed, setRefreshed] = useState("");
  const [away, setAway] = useState(false);
  const opened = useRef<Window | null>(null);
  const timer = useRef<number | undefined>(undefined);
  // Listening for the answer lasts until it comes, the sign-in is cancelled or started again, or the screen goes: not until the
  // window is seen closed (its answer may be read after that) and not while the screen redraws (new words, the sign-in's name
  // unknown for one draw), so the words and the name are read from refs and the effect is set up once.
  const live = useRef(false);
  const sentFor = useRef(name);
  const words = useRef(t);
  words.current = t;
  const current = useRef(name);
  current.current = name;

  const stopWatching = useCallback(() => window.clearInterval(timer.current), []);
  const stop = useCallback(() => {
    live.current = false;
    window.clearInterval(timer.current);
  }, []);

  const answered = useRef<(m: SignInAnnounced) => void>(() => undefined);
  useEffect(() => {
    const off = listen((m) => answered.current(m));
    answered.current = (m: SignInAnnounced) => {
      if (!live.current || (m.name && m.name !== sentFor.current)) return;
      stop();
      const t = words.current;
      if (m.outcome === "done") {
        setPhase("done");
        setText("");
        setRefreshed(m.again ? t("sign_in.return.refreshed", { address: m.again }) : "");
      } else if (m.outcome === "different") {
        setPhase("different");
        setText(t("sign_in.return.different", { address: m.address ?? "", expected: m.expected ?? "" }));
      } else if (m.outcome === "refused") {
        setPhase("refused");
        setText(refusedWords(m.error, m.detail, t));
      } else {
        setPhase("failed");
        setText(t(`sign_in.return.${m.outcome === "expired" ? "expired" : "failed"}`));
      }
    };
    return () => {
      off();
      stop();
    };
  }, [stop]);

  const cancel = useCallback(() => {
    stop();
    try {
      opened.current?.close();
    } catch {
      // Already gone.
    }
    opened.current = null;
    setText("");
    setPhase("idle");
  }, [stop]);

  const start = useCallback(async (account?: string) => {
    stop();
    sentFor.current = current.current;
    const t = words.current;
    setText("");
    setRefreshed("");
    setPhase("starting");
    if (inAppWindow()) {
      // The app's own window opens no pop-ups: the service's page opens in the person's browser, which comes back to a
      // page that only says how it went, and this screen asks the app for the outcome until it is known.
      setAway(true);
      let ticket = "";
      try {
        const started = await api.startSignIn(current.current, false, account, true);
        ticket = started.ticket ?? "";
        if (!ticket || !openInBrowser(started.url)) throw new Error("not opened");
      } catch (err) {
        setPhase("failed");
        setText(err instanceof Error && err.message === "not opened" ? t("sign_in.window.blocked") : problemText(err, t));
        return;
      }
      live.current = true;
      setPhase("waiting");
      timer.current = window.setInterval(() => {
        api.signInOutcome(ticket).then(
          (o) => {
            if (o.outcome === "waiting") return;
            answered.current({
              outcome: o.outcome,
              name: o.name ?? sentFor.current,
              error: o.error ?? "",
              detail: o.detail ?? "",
              address: o.address ?? undefined,
              expected: o.expected ?? undefined,
              again: o.again ?? undefined,
            });
          },
          () => undefined, // A read that failed is asked again at the next tick.
        );
      }, WATCH_MS);
      return;
    }
    setAway(false);
    // Opened at the click, empty, so the browser lets it through; it is sent to the service's page when that is known.
    const win = window.open("", "_blank");
    if (!win) {
      setPhase("blocked");
      setText(t("sign_in.window.blocked"));
      return;
    }
    opened.current = win;
    try {
      const started = await api.startSignIn(current.current, false, account);
      win.location.href = started.url;
    } catch (err) {
      try {
        win.close();
      } catch {
        // Already gone.
      }
      setPhase("failed");
      setText(problemText(err, t));
      return;
    }
    live.current = true;
    setPhase("waiting");
    timer.current = window.setInterval(() => {
      if (!opened.current?.closed) return;
      // Closed: the window stops being watched, but the answer it sent is still waited for (it may be read after this).
      stopWatching();
      // Closed without an answer so far: the sign-in's own status says whether it went through.
      api.signIns().then(
        (all) => {
          if (!live.current) return;
          const found = all.find((s) => s.name === sentFor.current);
          if (found?.status === "signed_in") setPhase("done");
          else {
            setPhase("closed");
            setText(t("sign_in.window.closed"));
          }
        },
        () => {
          if (!live.current) return;
          setPhase("closed");
          setText(t("sign_in.window.closed"));
        },
      );
    }, WATCH_MS);
  }, [stop, stopWatching]);

  const busy = phase === "starting" || phase === "waiting";
  return { start, cancel, phase, text, refreshed, busy, problem: phase === "done" ? "" : text, away };
}
