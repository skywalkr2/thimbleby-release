// The navigation (design 7.1): the groups and the bottom entries are fixed, and a plugin's panel adds an entry only under
// Work (its tab is `work`) or Records (`people`). Panels for Settings and Today do not appear here. What waits to go out is
// a tab of Follow-ups, and Connections and Add-ons are sections of Settings, so none of the three has an entry. An entry with
// something waiting for the person shows how many, and says in words what the number counts: Today's come from its own
// lines, the others from the one answer of what waits on each screen.
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, type S } from "../lib/api";
import { panelView, type View } from "../lib/views";
import { useWords } from "../lib/wording";
import { useTodayCount } from "../lib/today";
import { useWaiting } from "../lib/waiting";
import { useSides, useStableJustMe } from "../lib/sides";
import { recordView } from "../lib/views";
import type { IconName } from "../ui/Icon";

export interface NavEntry {
  view: View;
  label: string;
  icon?: IconName;
  /** The project of the side this entry is: drawn as that side's dot, in place of the icon, when sides are colored. */
  side?: string;
  /** A plugin's panel has no icon of its own: its first letter stands in. */
  glyph?: string;
  count?: number | null;
  /** What the count says in words, for the screen reader: "3 to send". */
  countWords?: string;
  /** Shown a step in from its group's own entries (a plugin's panel, or a view the person reaches less often). */
  sub?: boolean;
}

export interface NavModel {
  today: NavEntry;
  /** The week of meetings and dates, beside Today. */
  schedule: NavEntry;
  /** Whether there is no side beside Personal: the group below then has no name, and no work words anywhere in it. */
  justMe: boolean;
  /** What the first group is called: the work group, or, with no work, a plain "your things". */
  workTitle: string;
  work: NavEntry[];
  /** The projects among `records`: Personal and each side by its own mark, or Projects. */
  projects: NavEntry[];
  /** Personal and each side, as a group of their own when there is a side beside Personal; empty otherwise (they are then among `records`). */
  sides: NavEntry[];
  records: NavEntry[];
  bottom: NavEntry[];
}

const some = (n: number | null | undefined): number | null => (n ? n : null);

const PANELS_KEY = "cockpit:nav:panels";
type NavPanel = Pick<S["PanelView"], "name" | "title" | "tab">;

function rememberedPanels(): NavPanel[] {
  try {
    const found: unknown = JSON.parse(window.localStorage.getItem(PANELS_KEY) ?? "[]");
    return Array.isArray(found) ? found.filter((p): p is NavPanel => !!p && typeof p.name === "string" && typeof p.title === "string" && typeof p.tab === "string") : [];
  } catch {
    return [];
  }
}

/** The add-ons' panels for the menu. Until they are read it is what this browser last read, so the entries the add-ons add do not
 * arrive after the screen draws and push every link below them down under the pointer; a read that fails keeps them too. */
export function useStablePanels(): NavPanel[] {
  const panels = useQuery({ queryKey: ["panels"], queryFn: () => api.panels() });
  const found = panels.data;
  useEffect(() => {
    if (!found) return;
    try {
      window.localStorage.setItem(PANELS_KEY, JSON.stringify(found.map((p) => ({ name: p.name, title: p.title, tab: p.tab }))));
    } catch {
      // Storage can be blocked; the menu is then drawn from what is read.
    }
  }, [found]);
  return found ?? rememberedPanels();
}

const STAGES_KEY = "cockpit:nav:stages";

/** Whether any kind of record has stages. Until the status is read it is what this browser last read, so the Stages entry
 * does not arrive after the screen draws and push the links below it down; a read that fails keeps it too. */
export function useStableHasStages(): boolean {
  const found = useQuery({ queryKey: ["status"], queryFn: api.status }).data?.has_stages;
  useEffect(() => {
    if (found === undefined) return;
    try {
      window.localStorage.setItem(STAGES_KEY, found ? "1" : "0");
    } catch {
      // Storage can be blocked; the menu is then drawn from what is read.
    }
  }, [found]);
  if (found !== undefined) return found;
  try {
    return window.localStorage.getItem(STAGES_KEY) === "1";
  } catch {
    return false;
  }
}

export function useNav(): NavModel {
  const { t, tn } = useWords();
  const panels = useStablePanels();
  const waiting = useWaiting();
  const needsYou = useTodayCount();
  const { personal, sides } = useSides();
  const justMe = useStableJustMe();
  const plugin = (tab: string, group: "work" | "records"): NavEntry[] =>
    panels
      .filter((p) => p.tab === tab)
      .map((p) => ({ view: panelView(p.name, group), label: p.title, glyph: [...p.title.trim()][0]?.toUpperCase() ?? "", sub: true }));
  // Personal and each side by its own name, each a link to that top project's page; a person with nothing beside Personal
  // has Personal alone, where Projects would be. With a side, the projects live inside each side's page. Anyone else (a
  // workspace with projects and no side) keeps Projects.
  // Each by its side's dot (the same colored dot as everywhere a side is named), so the icon rail tells sides apart without letters;
  // a person with no colored sides has the grid icon.
  const named = [...(personal ? [{ view: recordView("project", personal), label: t("nav.personal"), project: personal }] : []), ...sides.map((s) => ({ view: recordView("project", s.project), label: s.name, project: s.project }))];
  const sideEntries: NavEntry[] = named.map((n) => ({ view: n.view, label: n.label, icon: "grid", side: n.project }));
  const projects: NavEntry[] = justMe || sides.length > 0 ? sideEntries : [{ view: "records/projects", label: t("nav.projects"), icon: "grid" }];
  // Stages is listed only while some kind of record has stages; the page still answers when opened by its address.
  const hasStages = useStableHasStages();
  const wait: NavEntry[] = !hasStages
    ? []
    : [
        { view: "work/stages", label: t("nav.stages"), icon: "layers", sub: true },
      ];
  return {
    today: { view: "today", label: t("nav.home"), icon: "home", count: some(needsYou), countWords: needsYou ? tn("nav.count.today", needsYou) : undefined },
    schedule: { view: "schedule", label: t("nav.schedule"), icon: "calendar" },
    justMe,
    workTitle: t(justMe ? "nav.work.just_me" : "nav.work"),
    work: [
      { view: "work/changed", label: t("nav.changed"), icon: "inbox", count: some(waiting?.changed.total), countWords: waiting?.changed.total ? tn("nav.count.changed", waiting.changed.total) : undefined },
      { view: "work/handled", label: t("nav.handled"), icon: "archive", count: some(waiting?.handled.total), countWords: waiting?.handled.total ? tn("nav.count.handled", waiting.handled.total) : undefined },
      { view: "work/followups", label: t("nav.followups"), icon: "send", count: some(waiting?.followups.total), countWords: waiting?.followups.total ? tn("nav.count.followups", waiting.followups.total) : undefined },
      { view: "work/open", label: t("nav.open"), icon: "check", count: some(waiting?.open.total), countWords: waiting?.open.total ? tn("nav.count.open", waiting.open.total) : undefined },
      ...wait,
      ...plugin("work", "work"),
    ],
    projects,
    sides: justMe || sides.length === 0 ? [] : sideEntries,
    records: [
      ...(justMe || sides.length === 0 ? projects : []),
      { view: "records/people", label: t("nav.people"), icon: "users" },
      { view: "records/files", label: t("nav.files"), icon: "folder" },
      { view: "records/notes", label: t("nav.notes"), icon: "note", sub: true },
      { view: "records/knowledge", label: t("nav.knowledge"), icon: "book", sub: true },
      ...plugin("people", "records"),
    ],
    bottom: [
      { view: "settings", label: t("nav.settings"), icon: "gear" },
    ],
  };
}
