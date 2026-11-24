// Teams (design 5.1, 7.13): the groups of people, as the same table with a detail pane that People is: Team and how many are in it;
// a row opens the detail, which names the people on it, and the team's page is where people are put on it and taken off. With no
// team on file the section is left out: a heading would stand over nothing.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type S } from "../lib/api";
import { recordView, viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { Actions } from "../ui/Actions";
import { ButtonLink } from "../ui/Button";
import { DefinitionList, Definition } from "../ui/DefinitionList";
import { ListDetail } from "../ui/ListDetail";
import { ListState } from "../ui/ListState";
import { RecordsTable, type TableColumn } from "../ui/RecordsTable";

/** The width the priority columns (name and people) need beside the pane. */
const TEAMS_FIT = 360;

export function Teams() {
  const { t } = useWords();
  const teams = useQuery({ queryKey: ["teams"], queryFn: api.teams });
  const people = useQuery({ queryKey: ["people"], queryFn: api.people });
  const [chosen, setChosen] = useState<string | null>(null);
  if (teams.isPending || (teams.isSuccess && teams.data.length === 0)) return null;
  const rows = [...(teams.data ?? [])].sort((a, b) => a.name.localeCompare(b.name));
  const selected = rows.find((x) => x.id === chosen) ?? null;
  const names = new Map((people.data ?? []).map((p) => [p.id, p.name]));
  const columns: TableColumn<S["TeamView"]>[] = [{ id: "people", header: t("team.members"), rank: 1, core: true, numeric: true, cell: (x) => (x.people.length > 0 ? x.people.length : "") }];
  return (
    <section className="panel-section" aria-labelledby="teams-title">
      <div className="heading">
        <h2 id="teams-title">{t("teams.title")}</h2>
      </div>
      <ListDetail
        title={selected?.name ?? ""}
        onClose={() => setChosen(null)}
        fit={TEAMS_FIT}
        detail={
          selected ? (
            <>
              <DefinitionList>
                <Definition>
                  <dt>{t("team.members")}</dt>
                  <dd>{selected.people.length > 0 ? selected.people.map((id) => <div key={id}>{names.get(id) ?? id}</div>) : t("teams.none_in")}</dd>
                </Definition>
              </DefinitionList>
              <Actions align="end">
                <ButtonLink variant="primary" href={viewHref(recordView("team", selected.id))}>
                  {t("records.open_page", { name: selected.name })}
                </ButtonLink>
              </Actions>
            </>
          ) : null
        }
      >
        <ListState query={teams} failed={t("teams.load_failed")} rows={2} shape="table">
          {() => (
            <RecordsTable
              label={t("teams.title")}
              name={{
                header: t("teams.col.name"),
                title: (x) => x.name,
                cell: (x, open) => (
                  <a href={viewHref(recordView("team", x.id))} onClick={open}>
                    {x.name}
                  </a>
                ),
              }}
              columns={columns}
              groups={[{ id: "teams", title: t("teams.title"), rows }]}
              rowKey={(x) => x.id}
              selected={chosen}
              onSelect={(x) => setChosen(x.id)}
            />
          )}
        </ListState>
      </ListDetail>
    </section>
  );
}
