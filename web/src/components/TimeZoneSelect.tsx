// A time zone picked from one list (design 7.8, 7.12): a button that shows the city and opens a list of cities, never a box to
// type in. Typing a few letters on the open list jumps to the city that starts with them. The setting holds the zone's id; the
// person only ever sees cities, with the zone's general name and its offset.
import { useMemo } from "react";
import { zoneChoices, zoneOffset } from "../lib/time-zones";
import { Select } from "../ui/Select";

export function TimeZoneSelect(props: {
  id: string;
  value: string;
  /** The ids of the zones to offer. */
  options: string[];
  onChange: (id: string) => void;
  disabled?: boolean;
  describedBy?: string;
}) {
  const all = useMemo(() => zoneChoices(props.options.includes(props.value) || !props.value ? props.options : [props.value, ...props.options]), [props.options, props.value]);
  return (
    <Select
      id={props.id}
      value={props.value}
      disabled={props.disabled}
      aria-describedby={props.describedBy}
      filter={false}
      onChange={(e) => props.onChange(e.target.value)}
    >
      {all.map((c) => (
        <option key={c.id} value={c.id}>
          {c.id.includes("/") ? `${c.label} ${zoneOffset(c.id)}`.trim() : c.label}
        </option>
      ))}
    </Select>
  );
}
