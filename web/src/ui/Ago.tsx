// A recent moment as words ("3 weeks ago") with the exact day and time as its tooltip; the one way a table and a detail say when.
import { useAgo } from "../lib/ago";
import { dayAndTime } from "../lib/dates";

export function Ago(props: { iso: string | null | undefined }) {
  const ago = useAgo();
  const words = ago(props.iso);
  if (!props.iso || !words) return null;
  return <span title={dayAndTime(props.iso)}>{words}</span>;
}
