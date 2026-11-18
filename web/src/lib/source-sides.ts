// Saving which sides a connection serves: the one write both the setup question and the tick boxes make, the `sides` of each
// source in the `watch.sources` setting, read fresh so a change made meanwhile is noticed rather than overwritten.
import type { QueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { freshSettings } from "./settings-save";
import type { S } from "./api";

export const SOURCES = "watch.sources";

/** Sets the sides of the given sources, in the order of `order`. A save refused because the settings moved on is made again from
 * what is there now (twice at most), so an answer is never lost to a race. */
export async function setSourceSides(client: QueryClient, ids: string[], sides: string[], order: string[]): Promise<S["SettingsSaved"]> {
  for (let attempt = 1; ; attempt += 1) {
    try {
      const current = await freshSettings(client);
      const list = (current.items.find((i) => i.key === SOURCES)?.value ?? []) as Array<Record<string, unknown> & { id: string }>;
      const ordered = [...order.filter((id) => sides.includes(id)), ...sides.filter((id) => !order.includes(id))];
      const changes = { [SOURCES]: list.map((s) => (ids.includes(s.id) ? { ...s, sides: ordered } : s)) };
      return await api.saveSettings({ changes, reset: [], fingerprint: current.fingerprint });
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 409) || attempt >= 3) throw err;
    }
  }
}
