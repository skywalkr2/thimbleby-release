// What makes two entries of a day "the same thing said more than once", written once: the Month folds identical all-day entries
// into one with a count on this key, and the week's strip folds on the same one (its copy of the key in ScheduleGrid.tsx is to be
// replaced by this function when the Schedule's batches are merged).
export const entryFoldKey = (e: { kind: string; title: string; own: boolean; cancelled: boolean }): string => [e.kind, e.title, e.own, e.cancelled].join("|");
