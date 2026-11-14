// Used by lint-rule.test.ts: a bare refresh of every screen, which the lint rule must refuse.
import type { QueryClient } from "@tanstack/react-query";

export function refreshEverything(client: QueryClient) {
  return client.invalidateQueries();
}
