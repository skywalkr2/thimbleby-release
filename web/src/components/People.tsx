// People (design 7.13, 7.14): everyone the workspace works with, as the same table with a detail pane that Projects is: Name,
// Role (who they are, beside a side of work), Open items, Waiting on them (how long the longest has waited, a warning pill) and
// Last contact, with the row's menu at the end. A row, Enter on it or its name opens the detail
// pane beside the table (over it when the priority columns would not fit, a drawer on a narrower window); the name's link is
// the person's page for a new tab. Adding and editing happen in a drawer, so the table
// stays in view and the new row appears beside the form. Organizations are kept here too, since a person works for one.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type S } from "../lib/api";
import { useAgo } from "../lib/ago";
import { day } from "../lib/dates";
import { whoTheyAre } from "../lib/people-who";
import { onSides, useSideFilter, useSides } from "../lib/sides";
import { viewHref, recordView } from "../lib/views";
import { useWords } from "../lib/wording";
import { Button, ButtonLink } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { FormField } from "../ui/FormField";
import { ListDetail } from "../ui/ListDetail";
import { Pill } from "../ui/Pill";
import { RecordsTable, type TableColumn } from "../ui/RecordsTable";
import { InRowActions } from "../ui/rowContext";
import { PersonAvatar } from "./PersonAvatar";
import { filterBarShown } from "../lib/filterbar";
import { useSideSlot } from "../lib/marks";
import { FilteredEmpty } from "../ui/FilteredEmpty";
import { ListState } from "../ui/ListState";
import { Organizations } from "./Organizations";
import { Teams } from "./Teams";
import styles from "./People.module.css";
import { PersonDrawer, heldReach } from "./PersonForm";
import { PersonLookLine } from "./PersonLookLine";
import { RecordConversation } from "./RecordConversation";
import { SideFilter } from "./SideFilter";
import { RowMenu } from "./RowMenu";
import { usePersonMenu } from "./PersonMenu";

import { PageHeader } from "../ui/PageHeader";
import { Select } from "../ui/Select";
import { Actions } from "../ui/Actions";
import { DefinitionList, Definition } from "../ui/DefinitionList";
/** The organization filter's choices besides one on file: everyone, and people with none. */
const ALL = "";
const NONE = "\u0001none";

/** The width the priority columns (name, role, organization, open items and the menu) need beside the pane. */
const PEOPLE_FIT = 520;

export function People() {
  const { t, tn } = useWords();
  const people = useQuery({ queryKey: ["people"], queryFn: api.people });
  const orgs = useQuery({ queryKey: ["organizations"], queryFn: api.organizations });
  // With no side beside Personal a person is said by who they are to you: no role, organization or list of organizations.
  const { justMe, personal, sides } = useSides();
  // With a side beside Personal the list can be narrowed to one side; a person on no known side shows under every choice.
  const side = useSideFilter();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<S["PersonView"] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [org, setOrg] = useState(ALL);
  const all = [...(people.data ?? [])]
    .filter((p) => p.is_pm || onSides(p.sides, side.choice))
    .sort((a, b) => (a.is_pm === b.is_pm ? a.name.localeCompare(b.name) : a.is_pm ? -1 : 1));
  const rows = all.filter((p) => org === ALL || (org === NONE ? !p.org : p.org === org));
  const selected = all.find((p) => p.id === chosen) ?? null;
  const who = (p: S["PersonView"]) => whoTheyAre(p, personal, sides, t);

  const menu = usePersonMenu(setEditing);

  const tags = (p: S["PersonView"]) => (
    <>
      {p.is_pm && <Pill tone="neutral">{t("setup.you")}</Pill>}
      {p.status === "left" && <Pill tone="neutral">{t("setup.left")}</Pill>}
      {p.track_only && <Pill tone="neutral">{t("people.watching")}</Pill>}
    </>
  );
  const reach = (p: S["PersonView"]) => Object.entries(heldReach(p.how_to_reach)).flatMap(([kind, values]) => values.map((value) => `${kind}: ${value}`));
  const slotOf = useSideSlot();
  const ago = useAgo();
  // The columns of the table at a glance: who they are, what is open with them, who has kept the person waiting and when they last spoke.
  // A column no one has anything in is not drawn.
  const columns: TableColumn<S["PersonView"]>[] = [
    { id: "role", header: justMe ? t("people.col.who") : t("people.col.role"), rank: 1, core: true, cell: (p) => who(p) },
    { id: "open", header: t("people.col.open"), rank: 1, core: true, numeric: true, cell: (p) => (p.open_items > 0 ? p.open_items : "") },
    {
      id: "waiting",
      header: t("people.col.waiting"),
      rank: 1,
      core: true,
      cell: (p) =>
        p.waiting_on_them > 0 ? (
          <Pill tone="warn" title={tn("people.waiting_on", p.waiting_on_them)}>
            {p.waiting_days != null ? tn("people.waiting_days", p.waiting_days) : tn("people.waiting_on", p.waiting_on_them)}
          </Pill>
        ) : (
          ""
        ),
    },
    { id: "last", header: t("people.col.last"), rank: 2, cell: (p) => (p.last_contact ? ago(p.last_contact) : "") },
  ];
  const orgFilterShown = !justMe && (orgs.data ?? []).length > 1 && filterBarShown(all.length, org !== ALL);
  const filter = orgFilterShown ? (
    <FormField id="people-org" label={t("people.filter_org")} labelHidden className={styles.orgFilter} data-size="content">
      <Select id="people-org" value={org} onChange={(e) => setOrg(e.target.value)}>
        <option value={ALL}>{t("people.all_orgs")}</option>
        {(orgs.data ?? []).map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
        <option value={NONE}>{t("people.no_org")}</option>
      </Select>
    </FormField>
  ) : null;
  // What the page holds, said once under the title: how many people and, beside sides, how many organizations.
  const summary = people.data && !people.isError ? [tn("people.count", people.data.length), !justMe && orgs.data && !orgs.isError ? tn("orgs.count", orgs.data.length) : ""].filter(Boolean).join(", ") : undefined;

  return (
    <section className="panel-section" aria-labelledby="people-title">
      <PageHeader
        id="people-title"
        title={t("setup.people")}
        subtitle={summary}
        reserveSubtitle={people.isPending}
        filters={
          <>
            <SideFilter holds={(people.data ?? []).length} />
            {filter}
          </>
        }
        primary={
          <Button variant="primary" onClick={() => setAdding(true)}>
            {t("setup.add_person")}
          </Button>
        }
      />
      <PersonLookLine />
      <ListDetail
        title={selected?.name ?? ""}
        onClose={() => setChosen(null)}
        fit={PEOPLE_FIT}
        detail={selected ? <PersonDetail person={selected} justMe={justMe} tags={tags(selected)} reach={reach(selected)} onEdit={() => setEditing(selected)} /> : null}
      >
        <ListState query={people} failed={t("people.load_failed")} rows={4} shape="table">
          {() =>
            all.length === 0 ? (
              side.choice !== "all" ? (
                <FilteredEmpty text={t("sides.empty.people", { side: side.named })} label={t("sides.empty.show_all")} onClear={() => side.set("all")} />
              ) : (
                <EmptyState text={t(justMe ? "setup.no_people.just_me" : "setup.no_people")} action={{ label: t("setup.add_person"), onClick: () => setAdding(true) }} />
              )
            ) : (
              <>
                {rows.length === 0 ? (
                  <FilteredEmpty text={t("people.none_here")} onClear={() => setOrg(ALL)} />
                ) : (
                  <RecordsTable
                    label={t("setup.people")}
                    name={{
                      header: t("people.col.name"),
                      title: (p) => p.name,
                      cell: (p, open) => (
                        <span className={styles.who}>
                          <PersonAvatar name={p.name} slot={slotOf((p.sides ?? [])[0])} size="md" />
                          <a href={viewHref(recordView("person", p.id))} onClick={open}>
                            {p.name}
                          </a>
                          {tags(p)}
                        </span>
                      ),
                    }}
                    columns={columns}
                    groups={[{ id: "people", title: t("setup.people"), rows }]}
                    rowKey={(p) => p.id}
                    selected={chosen}
                    onSelect={(p) => setChosen(p.id)}
                    actionsHeader={t("people.col.actions")}
                    actions={(p) => (
                      <InRowActions.Provider value={true}>
                        <RowMenu label={p.name} actions={menu(p)} />
                      </InRowActions.Provider>
                    )}
                  />
                )}
              </>
            )
          }
        </ListState>
      </ListDetail>
      {!justMe && !people.isError && <Organizations />}
      {!people.isError && <Teams />}
      {adding && <PersonDrawer onClose={() => setAdding(false)} onSaved={(id) => setChosen(id)} />}
      {editing && <PersonDrawer person={editing} onClose={() => setEditing(null)} />}
    </section>
  );
}

function PersonDetail(props: { person: S["PersonView"]; justMe: boolean; tags: React.ReactNode; reach: string[]; onEdit: () => void }) {
  const { t, tn } = useWords();
  const p = props.person;
  const fact = (label: string, value: React.ReactNode) =>
    value ? (
      <Definition>
        <dt>{label}</dt>
        <dd>{value}</dd>
      </Definition>
    ) : null;
  return (
    <>
      <Actions align="end">{props.tags}</Actions>
      <DefinitionList>
        {fact(t("people.col.relation"), p.relation)}
        {!props.justMe && fact(t("people.col.role"), p.role)}
        {!props.justMe && fact(t("people.col.org"), p.org_name)}
        {fact(t("setup.first_name"), p.first_name)}
        {fact(t("setup.aliases"), p.aliases.join(", "))}
        {fact(t("people.col.reach"), props.reach.length ? props.reach.map((line) => <div key={line}>{line}</div>) : null)}
        {fact(t("people.col.open"), p.open_items > 0 ? tn("people.open_with", p.open_items) : null)}
        {fact(t("people.col.waiting"), p.waiting_on_them > 0 ? [tn("people.waiting_on", p.waiting_on_them), p.waiting_days != null ? tn("people.waiting_longest", p.waiting_days) : ""].filter(Boolean).join(" · ") : null)}
        {fact(t("people.col.last"), p.last_contact ? day(p.last_contact) : null)}
      </DefinitionList>
      <Actions align="end">
        <ButtonLink href={viewHref(recordView("person", p.id))}>
          {t("records.open_page", { name: p.name })}
        </ButtonLink>
        <Button variant="primary" onClick={props.onEdit}>
          {t("setup.edit")}
        </Button>
      </Actions>
      <RecordConversation key={p.id} kind="person" id={p.id} />
    </>
  );
}
