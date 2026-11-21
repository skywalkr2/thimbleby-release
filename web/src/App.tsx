// The app shell (design 7.1): one grid with the header across the top, the sidebar on the left (a bottom bar on a phone) and
// the content area, which is the only thing that changes when the view does. Every view is a link in the address's fragment.
import { useQuery } from "@tanstack/react-query";
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type S } from "./lib/api";
import { useBuildLabel } from "./lib/build-label";
import { useShortcuts } from "./lib/keys";
import { ConnectionProvider } from "./lib/connection";
import { useLive } from "./lib/live";
import { ReadyMark } from "./lib/ready";
import { applyBrand } from "./lib/theme";
import { showNewLines } from "./lib/queue-hold";
import { useMediaQuery, useNarrow } from "./lib/media";
import { RestartAnnouncer, RestartProvider, useRestart } from "./lib/restart";
import { useRestartWhat } from "./lib/restart-for";
import { useSignInReturn } from "./lib/sign-in-return";
import { useToasts } from "./lib/toasts";
import { EVENT_PAGE, canonical, fromHash, movedTo, parseView, recordView, settingsView, toHash, type SettingsSection, type View } from "./lib/views";
import { screenOf, type Screen } from "./lib/walkthrough";
import { useWords } from "./lib/wording";
import { Addons } from "./components/Addons";
import { Ask } from "./components/Ask";
import { SEARCH_FIELD } from "./components/SearchBox";
import { Feedback } from "./components/Feedback";
import { AlphaNumbers } from "./components/AlphaNumbers";
import { ReportProblem } from "./components/ReportProblem";
import { OpenReportProvider, type OpenReport } from "./lib/open-report";
import { FollowUps } from "./components/FollowUps";
import { HandIn } from "./components/HandIn";
import { NotAvailable } from "./components/NotAvailable";
import { MissedOneProvider } from "./components/MissedOne";
import { Panel } from "./components/Panel";
import { restoreFocus } from "./components/ModalPanel";
import { type AddRequest } from "./components/Sources";
import { Today } from "./components/Today";
import { ShortcutHelp } from "./components/ShortcutHelp";
import { WhatChanged } from "./components/WhatChanged";
import { BottomBar } from "./shell/BottomBar";
import { Header } from "./shell/Header";
import { Sidebar, useSidebarMode } from "./shell/Sidebar";
import { useNeedsYouNotices } from "./components/NeedsYouNotices";
import shell from "./shell/Shell.module.css";
import { Button } from "./ui/Button";
import { BannerFallback, BannerHome } from "./ui/BannerSlot";
import { useServedVersion } from "./lib/update-ready";
import { ScreenBoundary } from "./ui/PartBoundary";
import { Skeleton } from "./ui/Skeleton";
import { lazyScreen } from "./lib/lazy-screen";

// Each main screen is its own chunk, loaded on first visit. The shell and Today are in the first load, and so are the
// screens Today's own detail already draws (Follow-ups, What changed, Add-ons, panels), which share their code with it.
const AiCompare = lazyScreen(() => import("./components/AiCompare"), "AiCompare");
const Files = lazyScreen(() => import("./components/Files"), "Files");
const Notes = lazyScreen(() => import("./components/Notes"), "Notes");
const OpenItems = lazyScreen(() => import("./components/OpenItems"), "OpenItems");
const Handover = lazyScreen(() => import("./components/Handover"), "Handover");
const Schedule = lazyScreen(() => import("./components/Schedule"), "Schedule");
const Quality = lazyScreen(() => import("./components/Quality"), "Quality");
const Knowledge = lazyScreen(() => import("./components/Knowledge"), "Knowledge");
const People = lazyScreen(() => import("./components/People"), "People");
const ProjectsOrPersonal = lazyScreen(() => import("./components/Projects"), "ProjectsOrPersonal");
const ConnectedEventPage = lazyScreen(() => import("./components/ConnectedEventPage"), "ConnectedEventPage");
const RecordPage = lazyScreen(() => import("./components/RecordPage"), "RecordPage");
const RuleReview = lazyScreen(() => import("./components/RuleReview"), "RuleReview");
const SeriesPage = lazyScreen(() => import("./components/SeriesPage"), "SeriesPage");
const loadSettings = () => import("./components/Settings");
const Settings = lazyScreen(loadSettings, "Settings");
const SettingsFrame = lazyScreen(loadSettings, "SettingsFrame");
const Sources = lazyScreen(() => import("./components/Sources"), "Sources");
const StyleGuide = lazyScreen(() => import("./components/StyleGuide"), "StyleGuide");
const Stages = lazyScreen(() => import("./components/Stages"), "Stages");
const Handled = lazyScreen(() => import("./components/Handled"), "Handled");
const SinceYesterday = lazyScreen(() => import("./components/SinceYesterday"), "SinceYesterday");
const Walkthrough = lazyScreen(() => import("./components/Walkthrough"), "Walkthrough");
export function App(props: { rc: S["RuntimeConfig"] }) {
  const live = useLive();
  // What the app is called is read again after any saved change, so a new name shows in the header at once, with no reload.
  const fresh = useQuery({ queryKey: ["runtime-config"], queryFn: api.runtimeConfig, initialData: props.rc, staleTime: Infinity });
  // A new accent color shows at once, with no reload: the page's brand colors follow what is saved.
  useServedVersion(fresh.data.version);
  const brand = fresh.data.brand_color;
  useEffect(() => applyBrand(brand), [brand]);
  return (
    <RestartProvider hellos={live.hellos}>
      <MissedOneProvider>
        <ConnectionProvider live={live}>
          <Shell rc={fresh.data} live={live} />
        </ConnectionProvider>
      </MissedOneProvider>
    </RestartProvider>
  );
}

/** The style guide is for development and demo workspaces only. */
const styleGuideShown = (rc: S["RuntimeConfig"]) => rc.demo || import.meta.env.DEV;

/** The first visible element that matches, so a control that exists twice (a field and an icon) is found where it shows. */
/** The search key: the cursor goes to the search field that is showing. */
function focusSearch() {
  visible(`[${SEARCH_FIELD}]`)?.focus();
}

function visible(selector: string): HTMLElement | null {
  const all = Array.from(document.querySelectorAll<HTMLElement>(selector));
  return all.find((el) => el.getClientRects().length > 0) ?? all[0] ?? null;
}

/** The width from which Ask is a pane beside the content rather than a dialog over it. */
const ASK_PANE_QUERY = "(min-width: 1440px)";

function Shell(props: { rc: S["RuntimeConfig"]; live: ReturnType<typeof useLive> }) {
  const { rc, live } = props;
  const buildLabel = useBuildLabel();
  const { t } = useWords();
  const { undoLast, push } = useToasts();
  const handedBack = useSignInReturn();
  useNeedsYouNotices();
  const narrow = useNarrow(rc.narrow_below_px);
  // From the desktop width Ask is a pane at the right edge beside the content; below it, a dialog (design 7.13).
  const wide = useMediaQuery(ASK_PANE_QUERY);
  const sidebar = useSidebarMode();
  const [handIn, setHandIn] = useState(false);
  const [help, setHelp] = useState(false);
  const [feedback, setFeedback] = useState(false);
  const [report, setReport] = useState(false);
  // The alpha numbers, and the words a report starts with when the person shares them.
  const [alpha, setAlpha] = useState(false);
  const [reportWords, setReportWords] = useState<string | undefined>(undefined);
  // The Ask box, with the question it opens on when a screen suggests one.
  const [ask, setAsk] = useState<{ question?: string; reveal?: string } | null>(null);
  const [view, setView] = useView();
  // The setup walkthrough opens at a screen when a line elsewhere sends the person to a step.
  const [guideAt, setGuideAt] = useState<{ screen: Screen; n: number } | null>(null);
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup });
  const focusFirstGo = useFocusFirstGo();
  // Sources opens on the form that adds one when Today or a sign-in sends the person there.
  const [addSource, setAddSource] = useState<AddRequest | null>(null);
  // Settings opens on the form that adds an AI account when a Today line sends the person there.
  const [addAccount, setAddAccount] = useState<number | null>(null);
  // A screen that puts focus somewhere of its own on opening (a step's heading, a form) keeps it.
  const ownFocus = useRef(false);
  // Set when the walkthrough sent the person to another screen: that screen then offers the way back to the step.
  const [fromSetup, setFromSetup] = useState(false);
  const leaveSetup = (go: () => void) => () => {
    setFromSetup(true);
    go();
  };
  const openAddSource = (plugin: string | null = null, services = false) => {
    ownFocus.current = true;
    setAddSource({ plugin, n: Date.now(), services });
    setView(settingsView("connections"));
  };
  const openGuide = (step?: string) => {
    // The walkthrough puts focus on its own heading.
    ownFocus.current = true;
    const screen = step && setup.data ? screenOf(setup.data.steps, step) : null;
    setGuideAt(screen ? { screen, n: Date.now() } : null);
    setView("setup");
  };
  // Where a record's page goes back to: the screen it was opened from.
  const origin = useRef<View>("today");
  const openRecord = (kind: string, id: string) => {
    if (parseView(view).type !== "record") origin.current = view;
    setView(recordView(kind, id));
  };
  const shown = parseView(view);
  // The grid of what each account can do belongs to Settings, so Settings stays marked in the navigation.
  // A page of an event the calendar holds belongs to the screen it was opened from; the rules to look over belong to Knowledge.
  const navView: View =
    view === "settings/ai-compare" || (shown.type === "core" && shown.view === "settings")
      ? "settings"
      : shown.type === "record" && shown.kind === EVENT_PAGE
        ? origin.current
        : view === "records/rules-review"
          ? "records/knowledge"
          : // A person's page and an organization's belong to People, so that entry stays marked, even when the page is gone.
            shown.type === "record" && (shown.kind === "person" || shown.kind === "organization")
            ? "records/people"
            : view;
  const inWalkthrough = shown.type === "core" && shown.view === "setup";
  // A new workspace's first visit opens the walkthrough by itself, once: the server says whether it should (it has not
  // been closed or finished, and setup is not done). A person who arrives at another screen, or has already opened
  // something on Today (the hand-in box, Ask, help or feedback), is not taken from it, so nothing they typed is lost.
  // An address that names Today (#today) is the person asking for Today: setup never takes them from it, whether the
  // address named it when the page opened or the person went there while setup was still being read.
  const named = () => window.location.hash.replace(/^#\/?/, "") !== "";
  const addressNamedAView = useRef(named());
  const autoOpened = useRef(false);
  useEffect(() => {
    if (autoOpened.current || !setup.data) return;
    autoOpened.current = true;
    const busy = handIn || ask !== null || help || feedback || report;
    if (setup.data.walkthrough?.open && shown.type === "core" && shown.view === "today" && !busy && !addressNamedAView.current && !named()) setView("setup");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setup.data]);
  const handlers = useMemo(
    () => ({ undo: undoLast, hand_in: () => setHandIn(true), ask: focusSearch, help: () => setHelp(true), show_new: showNewLines }),
    [undoLast],
  );
  const keys = rc.shortcuts;
  useShortcuts(keys, handlers);
  // The tab says whose workspace it is and what the app is called, from the wording sheet, so the product's name shows there.
  useEffect(() => {
    document.title = t("app.tab_title", { workspace: rc.workspace_name, app: t("app.name") });
  }, [rc.workspace_name, t]);

  // After going to another view (not on the first load), focus moves to the new view's heading.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    window.scrollTo?.(0, 0);
    // Settings and Handled for you put the cursor in their first field themselves; Connections and Add-ons, which sit in
    // Settings' frame, take it on their own heading (the frame's title is the same on every page of Settings).
    const now = parseView(view);
    const ownScreen = now.type === "core" && now.view === "settings" && (now.section === "connections" || now.section === "addons");
    if (now.type === "core" && !ownScreen && (now.view === "settings" || now.view === "work/handled")) {
      ownFocus.current = false;
      return;
    }
    if (ownFocus.current) {
      ownFocus.current = false;
      return;
    }
    const selector = ownScreen || (now.type === "core" && now.view === "settings/ai-compare") ? "main [data-section-heading]" : "main h1";
    const take = (heading: HTMLElement) => {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    };
    const heading = document.querySelector<HTMLElement>(selector);
    if (heading) {
      take(heading);
      return;
    }
    // A screen that is still loading has no heading yet: the cursor goes to it when it appears, unless the person has
    // already put the cursor somewhere else in the page (it may still be on the link that opened the screen), and stops
    // waiting after a few seconds.
    const main = document.getElementById("main");
    const openedFrom = document.activeElement;
    if (!main || typeof MutationObserver === "undefined") return;
    const watcher = new MutationObserver(() => {
      const found = document.querySelector<HTMLElement>(selector);
      if (!found) return;
      watcher.disconnect();
      const at = document.activeElement;
      if (!at || at === document.body || at === main || at === openedFrom) take(found);
    });
    watcher.observe(main, { childList: true, subtree: true });
    const stop = window.setTimeout(() => watcher.disconnect(), 5000);
    return () => {
      watcher.disconnect();
      window.clearTimeout(stop);
    };
  }, [view]);

  const restart = useRestart();
  const what = useRestartWhat();
  const restartNow = useRef(restart.now);
  restartNow.current = restart.now;
  // A change that needs a restart says so with a toast that holds the button; the status chip keeps it afterwards.
  useEffect(() => {
    if (restart.phase !== "asking") return;
    push({ message: t("restart.toast"), action: { label: t("restart.now"), run: () => restartNow.current() }, yields: true });
  }, [restart.phase, push, t]);

  const body = (() => {
    if (shown.type === "panel") return <Panel key={shown.name} name={shown.name} onOpenRecord={openRecord} />;
    if (shown.type === "record" && shown.kind === "series") {
      return <SeriesPage key={shown.id} id={shown.id} onBack={() => setView(origin.current)} />;
    }
    // A connected calendar's event the app keeps no entry for has a read-only page of its own, not a record.
    if (shown.type === "record" && shown.kind === EVENT_PAGE) {
      return <ConnectedEventPage key={shown.id} id={shown.id} onBack={() => setView(origin.current)} />;
    }
    if (shown.type === "record") {
      return <RecordPage key={`${shown.kind}:${shown.id}`} kind={shown.kind} id={shown.id} onBack={() => setView(origin.current)} />;
    }
    // A screen reached from Settings keeps the Settings side bar, so every other section is one choice away.
    const framed = (under: SettingsSection | undefined, body: ReactNode, subpage = false) => (
      <SettingsFrame under={under} subpage={subpage} choose={(section) => setView(settingsView(section))}>
        {body}
      </SettingsFrame>
    );
    switch (shown.view) {
      case "today":
        return (
          <Today
            workspace={rc.workspace_name}
            onView={setView}
            onAddSource={() => openAddSource(null, true)}
            onOpenRecord={openRecord}
            onOpenGuide={openGuide}
            onHandIn={() => setHandIn(true)}
            onOpenAnswer={(reveal) => setAsk({ reveal })}
            shortcuts={rc.shortcuts}
            onAddAccount={() => {
              setAddAccount(Date.now());
              setView(settingsView("ai"));
            }}
          />
        );
      case "schedule":
        return <Schedule />;
      case "work/changed":
        return <WhatChanged onOpenGuide={openGuide} />;
      case "work/since":
        return <SinceYesterday onOpenRecord={openRecord} onBack={() => setView("work/changed")} />;
      case "work/handled":
        return <Handled />;
      case "work/followups":
        return <FollowUps />;
      case "work/open":
        return <OpenItems />;
      case "work/stages":
        return <Stages />;
      case "records/projects":
        return <ProjectsOrPersonal onBack={() => setView(origin.current)} />;
      case "records/people":
        return <People />;
      case "records/files":
        return <Files />;
      case "records/notes":
        return <Notes onHandIn={() => setHandIn(true)} />;
      case "records/knowledge":
        return <Knowledge onOpenReview={() => setView("records/rules-review")} />;
      case "records/rules-review":
        return <RuleReview onBack={() => setView("records/knowledge")} />;
      case "setup":
        return null;
      case "settings":
        // Connections and Add-ons are sections of Settings: each shows its own screen beside the Settings side bar.
        if (shown.section === "connections") {
          return framed(
            "connections",
            <Sources
              onAsk={(question) => setAsk({ question })}
              add={addSource}
              onAddOpened={() => setAddSource(null)}
              onOpenAddons={() => setView(settingsView("addons"))}
              onOpenLinks={() => setView(settingsView("links"))}
            />,
          );
        }
        if (shown.section === "addons") return framed("addons", <Addons />);
        return (
          <Settings
            onOpenGuide={openGuide}
            onChooseSource={openAddSource}
            onOpenKnowledge={() => setView("records/knowledge")}
            onOpenCompare={() => setView("settings/ai-compare")}
            section={shown.section}
            onSection={(section) => setView(settingsView(section))}
            addAccount={addAccount}
            onAddAccountOpened={() => setAddAccount(null)}
          />
        );
      case "settings/ai-compare":
        return framed(
          "ai",
          <AiCompare
            onBack={() => setView(settingsView("ai"))}
            onAdd={() => {
              setAddAccount(Date.now());
              setView(settingsView("ai"));
            }}
          />,
          true,
        );
      case "handover":
        return <Handover onBack={() => setView("today")} />;
      case "quality":
        return <Quality onBack={() => setView("today")} />;
      case "styleguide":
        return styleGuideShown(rc) ? <StyleGuide /> : <NotAvailable title={t("nav.styleguide")} onBack={() => setView("today")} />;
      case "not-here":
        return <NotAvailable title={t("not_here.title")} text={t("not_here.text")} back={t("not_here.back")} onBack={() => setView("today")} />;
      default:
        return null;
    }
  })();

  const askPane = ask !== null && wide && !narrow && !inWalkthrough;
  const overlays = (
    <>
      <RestartAnnouncer what={what} />
      {ask && !askPane && (
        <Ask
          initial={ask.question}
          reveal={ask.reveal}
          feedbackTo={rc.feedback_to}
          onClose={() => {
            setAsk(null);
            restoreFocus(() => visible(`[${SEARCH_FIELD}], [data-ask-button]`));
          }}
        />
      )}
      {feedback && (
        <Feedback
          view={view}
          version={rc.version}
          to={rc.feedback_to}
          onClose={() => {
            setFeedback(false);
            restoreFocus(() => visible("[data-feedback-button]"));
          }}
        />
      )}
      {alpha && (
        <AlphaNumbers
          onClose={() => {
            setAlpha(false);
            restoreFocus(() => visible("[data-feedback-button]"));
          }}
          onShare={
            rc.report_enabled
              ? (words) => {
                  setAlpha(false);
                  setReportWords(words);
                  setReport(true);
                }
              : undefined
          }
        />
      )}
      {report && (
        <ReportProblem
          initialWords={reportWords}
          onClose={() => {
            setReport(false);
            setReportWords(undefined);
            restoreFocus(() => visible("[data-feedback-button]"));
          }}
        />
      )}
      <ShortcutHelp open={help} onClose={() => setHelp(false)} keys={keys} />
    </>
  );
  if (inWalkthrough) {
    if (fromSetup) setFromSetup(false);
    return (
      <>
        <Suspense fallback={<Skeleton shape="form" rows={3} />}>
          <Walkthrough
            at={guideAt}
            onOpenPeople={leaveSetup(() => setView("records/people"))}
            onOpenAddons={leaveSetup(() => setView(settingsView("addons")))}
            // The box opens over the setup guide, which stays where it was: handing something in is not leaving setup.
            onHandIn={() => setHandIn(true)}
            onDone={() => {
              setView("today");
              focusFirstGo();
            }}
          />
          <ReadyMark />
        </Suspense>
        {handIn && <HandIn onClose={() => setHandIn(false)} />}
        {overlays}
      </>
    );
  }

  const skip = (event: React.MouseEvent) => {
    event.preventDefault();
    document.getElementById("main")?.focus();
  };
  const openFeedback = () => setFeedback(true);
  const openReport = rc.report_enabled ? () => setReport(true) : undefined;
  const openAlpha = () => setAlpha(true);
  const openReportWith: OpenReport | undefined = rc.report_enabled
    ? (words) => {
        setReportWords(words);
        setReport(true);
      }
    : undefined;
  return (
    <OpenReportProvider value={openReportWith}>
      <a href="#main" className="skip" onClick={skip}>
        {t("app.skip")}
      </a>
      <div className={[shell.app, sidebar.expanded ? "" : shell.rail].filter(Boolean).join(" ")} data-nav={sidebar.expanded ? "full" : "rail"}>
        <Header
          rc={rc}
          live={live}
          narrow={narrow}
          shortcuts={keys}
          onHandIn={() => setHandIn(true)}
          onOpenRecord={openRecord}
          onAsk={(question) => setAsk(question ? { question } : {})}
          onHelp={() => setHelp(true)}
          onFeedback={openFeedback}
          onReport={openReport}
          onAlpha={openAlpha}
          onOpenGuide={openGuide}
          onOpenQuality={() => setView("quality")}
          onOpenSettings={() => setView("settings")}
        />
        {!narrow && <Sidebar current={navView} expanded={sidebar.expanded} onToggle={sidebar.toggle} />}
        <BannerHome>
        <main id="main" className={shell.main} tabIndex={-1}>
          {fromSetup && (
            <p className={shell.backToSetup} data-back-to-setup="">
              <Button
                onClick={() => {
                  setFromSetup(false);
                  openGuide();
                }}
              >
                {t("app.back_to_setup")}
              </Button>
            </p>
          )}
          {handedBack && (
            <div className={shell.backToSetup} role="status" data-sign-in-handed-back="">
              <p>
                {handedBack.message} {t("sign_in.return.close_note")}
              </p>
              <Button onClick={handedBack.dismiss}>{t("sign_in.return.keep_here")}</Button>
            </div>
          )}
          <BannerFallback />
          {handIn && <HandIn onClose={() => setHandIn(false)} />}
          <ScreenBoundary key={toHash(view)}>
            <Suspense fallback={<Skeleton shape="form" rows={3} />}>
              {body}
              <ReadyMark />
            </Suspense>
          </ScreenBoundary>
        </main>
        </BannerHome>
        {askPane && (
          <Ask
            pane
            initial={ask?.question}
            reveal={ask?.reveal}
            feedbackTo={rc.feedback_to}
            onClose={() => {
              setAsk(null);
              restoreFocus(() => visible(`[${SEARCH_FIELD}], [data-ask-button]`));
            }}
          />
        )}
      </div>
      {narrow && (
        <BottomBar
          current={navView}
          version={buildLabel(rc)}
          onHandIn={() => setHandIn(true)}
          onOpenRecord={openRecord}
          onAsk={(question) => setAsk(question ? { question } : {})}
          onHelp={() => setHelp(true)}
          onFeedback={openFeedback}
          onReport={openReport}
          onAlpha={openAlpha}
          onOpenGuide={() => openGuide()}
        />
      )}
      {overlays}
    </OpenReportProvider>
  );
}

export type { View } from "./lib/views";

/** Which view is showing, kept in the address's #fragment so a refresh, the back button and a bookmark all keep it. */
function useView(): [View, (v: View) => void] {
  const [view, setViewState] = useState<View>(() => settled());
  useEffect(() => {
    const onHash = () => setViewState(settled());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const setView = (v: View) => {
    window.location.hash = toHash(v);
    setViewState(canonical(v));
  };
  return [view, setView];
}

/** The view the address names. A fragment that moved (Waiting to go out, Connections, Add-ons) is rewritten to the one that
 * took its place, so a bookmark opens it and the address then says where the person is. */
function settled(): View {
  const moved = movedTo(window.location.hash);
  if (moved) {
    try {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${moved}`);
    } catch {
      // The address can't be rewritten; the view still opens.
    }
  }
  return fromHash(window.location.hash);
}

/** Puts focus on Today's first-go line once it is on the page, after the walkthrough closes onto Today. The line may take a
 * moment to appear; the wait is short and gives up quietly when there is no such line. */
function useFocusFirstGo(): () => void {
  const [asked, setAsked] = useState(0);
  useEffect(() => {
    if (!asked) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      const row = document.querySelector<HTMLElement>('[data-queue-line="first_go"]');
      tries += 1;
      if (row) {
        window.clearInterval(timer);
        row.scrollIntoView?.({ block: "center" });
        row.focus();
        // A row taller than the pane that holds it can't be centered whole; its button must still be on the screen.
        row.querySelector("button")?.scrollIntoView?.({ block: "nearest" });
      } else if (tries >= 25) {
        window.clearInterval(timer);
      }
    }, 200);
    return () => window.clearInterval(timer);
  }, [asked]);
  return () => setAsked(Date.now());
}
