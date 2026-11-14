// Files that may still call `invalidateQueries()` with no arguments (a refresh of every screen). None do: a screen names what it
// changed (through `useWrite`, `useAct` or `refreshSince`) or asks `refreshEverything` in write.ts. `live.ts` (the reconnect) and `write.ts` are exempt in the rule itself.
export const BARE_INVALIDATE_EXCEPTIONS = [];
