// A read that failed stays "failed" while the app reads again by itself. A query with no data goes back to "pending" the moment a
// read starts, so a screen that draws its skeleton for pending would swap the alert and its Try again for the skeleton under the
// pointer; this keeps the failed state, and the last error's words, until a read answers.
import { useRef } from "react";

interface Failing {
  data: unknown;
  isError: boolean;
  error: unknown;
  errorUpdateCount?: number;
}

/** Whether the read failed and has not answered since (a read again in the background included), and the error it failed with. */
export function useLoadFailure(query: Failing): { failed: boolean; error: unknown } {
  const last = useRef<unknown>(null);
  if (query.isError) last.current = query.error;
  const failed = query.data === undefined && (query.isError || (query.errorUpdateCount ?? 0) > 0);
  if (!failed) last.current = null;
  return { failed, error: query.isError ? query.error : last.current };
}
