// Whether what the person just handed in will wait for their Start: Today already has the line asking to start the assistant.
// The toast then says so, with a way to Today, rather than saying the assistant is on it.
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { api } from "./api";
import type { ToastInput } from "./toasts";
import { toHash } from "./views";
import { useWords } from "./wording";

// The tier a hand-in is read on.
const EVERYDAY_TIER = "routine";
const WAITING_FOR_START = new Set(["first_go", "catch_up_go"]);

/** What the work just handed in waits for: the person's Start, a restart (work is held until then), an AI account for everyday
 * work (Today's line asks to add one), or nothing. */
export type Waits = false | "start" | "restart" | "account";

/** Reads Today's queue afresh and says what a line on Today asks of the person before the assistant works: Start, a restart, or neither. */
export function useWaitsForStart(): () => Promise<Waits> {
  const client = useQueryClient();
  return useCallback(async () => {
    try {
      const lines = await client.fetchQuery({ queryKey: ["today", "queue"], queryFn: api.todayQueue, staleTime: 0 });
      if (lines.some((line) => line.kind === "restart")) return "restart";
      if (lines.some((line) => line.kind === "no_account" && (line.names ?? []).includes(EVERYDAY_TIER))) return "account";
      return lines.some((line) => WAITING_FOR_START.has(line.kind)) ? "start" : false;
    } catch {
      return false;
    }
  }, [client]);
}

/** The toast for something handed in: that the assistant is on it, or that it waits for Start on Today (with a link there). */
export function useHandedToast(): (waits: Waits, done: string, waiting: string) => Omit<ToastInput, "undo"> {
  const { t } = useWords();
  return (waits, done, waiting) =>
    waits ? { message: waits === "restart" ? t("toast.handed_in_restart") : waits === "account" ? t("toast.handed_in_account") : waiting, action: { label: t("toast.go_today"), run: () => void (window.location.hash = toHash("today")) } } : { message: done };
}
