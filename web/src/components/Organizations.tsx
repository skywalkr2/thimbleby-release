// Organizations (design 5.1, 7.13): the companies and bodies people work for, a table with one row each, how many people work there
// and the other names it goes by. Adding
// and renaming happen in a drawer; removing acts at once with Undo, and an organization people still work for can't be removed.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { useFirstField } from "../lib/focus";
import { recordView, viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { Actions } from "../ui/Actions";
import { Button, ButtonLink } from "../ui/Button";
import { DefinitionList, Definition } from "../ui/DefinitionList";
import { Drawer } from "../ui/Drawer";
import { ListDetail } from "../ui/ListDetail";
import { ListState } from "../ui/ListState";
import { RecordsTable, type TableColumn } from "../ui/RecordsTable";
import { InRowActions } from "../ui/rowContext";
import { Field } from "./PersonForm";
import { RowMenu, type MenuAction } from "./RowMenu";

import { EmptyState } from "../ui/EmptyState";

/** The width the priority columns (name, people, side and the menu) need beside the pane. */
const ORGS_FIT = 420;

/** One labelled fact of the detail; nothing when there is none. */
const fact = (label: string, value: React.ReactNode) =>
  value ? (
    <Definition>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </Definition>
  ) : null;

export function Organizations() {
  const { t, tn } = useWords();
  const act = useAct();
  const orgs = useQuery({ queryKey: ["organizations"], queryFn: api.organizations });
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState<S["OrganizationView"] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const rows = [...(orgs.data ?? [])].sort((a, b) => a.name.localeCompare(b.name));
  const menu = (o: S["OrganizationView"]): MenuAction[] => [
    { id: "rename", label: t("setup.rename"), run: () => setRenaming(o) },
    {
      id: "remove", danger: true,
      label: t("setup.remove"),
      disabled: o.people > 0 || !!o.side,
      reason: t(o.side ? "orgs.remove_own" : "setup.org_remove_blocked"),
      run: () =>
        void act(
          () => api.removeOrganization(o.id),
          () => ({ message: t("toast.org_removed", { name: o.name }), undo: () => api.restoreOrganization(o.id) }),
        ),
    },
  ];
  const selected = rows.find((o) => o.id === chosen) ?? null;
  const columns: TableColumn<S["OrganizationView"]>[] = [
    { id: "people", header: t("orgs.col.people"), rank: 1, core: true, numeric: true, cell: (o) => (o.people > 0 ? o.people : "") },
    { id: "side", header: t("orgs.col.side"), rank: 1, core: true, cell: (o) => (o.side ? t(o.side_kind === "job" ? "orgs.side.job" : "orgs.side.business") : "") },
    { id: "aliases", header: t("orgs.col.aliases"), rank: 2, weight: 2, cell: (o) => o.aliases.join(", ") },
  ];
  return (
    <section className="panel-section" aria-labelledby="organizations-title">
      <div className="heading">
        <h2 id="organizations-title">{t("setup.organizations")}</h2>
        <Button variant="quiet" onClick={() => setAdding(true)}>
          {t("setup.add_organization")}
        </Button>
      </div>
      <ListDetail
        title={selected?.name ?? ""}
        onClose={() => setChosen(null)}
        fit={ORGS_FIT}
        detail={
          selected ? (
            <>
              <DefinitionList>
                {fact(t("orgs.col.people"), selected.people > 0 ? tn("orgs.people", selected.people) : t("orgs.no_people"))}
                {fact(t("orgs.col.side"), selected.side ? t(selected.side_kind === "job" ? "orgs.side.job" : "orgs.side.business") : null)}
                {fact(t("orgs.col.aliases"), selected.aliases.join(", "))}
                {fact(t("orgs.row.notes"), selected.notes)}
              </DefinitionList>
              <Actions align="end">
                <ButtonLink href={viewHref(recordView("organization", selected.id))}>{t("records.open_page", { name: selected.name })}</ButtonLink>
                <Button variant="primary" onClick={() => setRenaming(selected)}>
                  {t("setup.rename")}
                </Button>
              </Actions>
            </>
          ) : null
        }
      >
        <ListState query={orgs} failed={t("orgs.load_failed")} rows={3} shape="table">
          {() =>
            rows.length === 0 ? (
              <EmptyState text={t("setup.no_organizations")} />
            ) : (
              <RecordsTable
                label={t("setup.organizations")}
                name={{
                  header: t("orgs.col.name"),
                  title: (o) => o.name,
                  cell: (o, open) => (
                    <a href={viewHref(recordView("organization", o.id))} onClick={open}>
                      {o.name}
                    </a>
                  ),
                }}
                columns={columns}
                groups={[{ id: "organizations", title: t("setup.organizations"), rows }]}
                rowKey={(o) => o.id}
                selected={chosen}
                onSelect={(o) => setChosen(o.id)}
                actionsHeader={t("people.col.actions")}
                actions={(o) => (
                  <InRowActions.Provider value={true}>
                    <RowMenu label={o.name} actions={menu(o)} />
                  </InRowActions.Provider>
                )}
              />
            )
          }
        </ListState>
      </ListDetail>
      {adding && <OrganizationDrawer onClose={() => setAdding(false)} />}
      {renaming && <OrganizationDrawer org={renaming} onClose={() => setRenaming(null)} />}
    </section>
  );
}

function OrganizationDrawer(props: { org?: S["OrganizationView"]; onClose: () => void }) {
  const { t } = useWords();
  const act = useAct();
  const o = props.org;
  const [name, setName] = useState(o?.name ?? "");
  const [busy, setBusy] = useState(false);
  const first = useFirstField<HTMLFormElement>();
  const formId = `organization-form-${o?.id ?? "new"}`;
  const save = async () => {
    const wanted = name.trim();
    if (!wanted || busy) return;
    if (o && wanted === o.name) return props.onClose();
    setBusy(true);
    const done = o
      ? await act(
          () => api.editOrganization(o.id, { name: wanted }),
          () => ({ message: t("toast.renamed", { name: wanted }), undo: () => api.editOrganization(o.id, { name: o.name }) }),
        )
      : await act(
          () => api.addOrganization({ name: wanted }),
          (created) => ({ message: t("toast.added", { name: wanted }), undo: () => api.removeOrganization(created.id) }),
        );
    setBusy(false);
    if (done) props.onClose();
  };
  return (
    <Drawer
      open
      title={t(o ? "organization.rename_title" : "organization.add_title")}
      dirty={name !== (o?.name ?? "")}
      onClose={props.onClose}
      footer={
        <>
          <Button onClick={props.onClose}>{t("action.cancel")}</Button>
          <Button variant="primary" type="submit" form={formId} disabled={!name.trim() || busy} reason={t("setup.name_missing")}>
            {t(o ? "setup.save" : "setup.add_organization")}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        ref={first}
        className="setup-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <Field id={`org-${o?.id ?? "new"}`} label={t("setup.organization_name")} value={name} onChange={setName} required />
      </form>
    </Drawer>
  );
}
