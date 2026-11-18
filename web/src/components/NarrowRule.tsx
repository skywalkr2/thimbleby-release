// "Narrow the new one": the target of a rule that contradicts one in force, opened for the person to limit to some
// projects, or to every project but some, before both rules are kept (design 6.7). Only the projects can be limited here;
// what else the rule names stays as it is.
import { useQuery } from "@tanstack/react-query";
import { api, type S } from "../lib/api";
import { NarrowForm } from "./NarrowForm";

export function NarrowRule(props: { back: S["ReadBackView"] | null | undefined; onSave: (scope: S["Scope"]) => void; onCancel: () => void }) {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const applies = props.back?.applies;
  const named = (applies?.projects ?? []).map((p) => p.id);
  const scope: S["Scope"] = {
    task_kinds: [],
    records: [],
    filter: {},
    projects: named,
    people: [],
    scope: named.length > 0 ? "projects" : "workspace",
    except: (applies?.except ?? []).map((p) => p.id),
  };
  return <NarrowForm scope={scope} projects={(projects.data ?? []).filter((p) => !p.side)} onSave={props.onSave} onCancel={props.onCancel} />;
}
