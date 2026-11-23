// Today's lines for what the assistant learned (design 7.7, 7.18): one Review line for what it learned from inputs and
// from corrections the person has already left, and one for the catch-up list. Each opens its list: a row per thing,
// tagged by where it came from, with Keep as its one primary action and Just this time, Edit and Discard in its menu.
// Keep all is offered only for glossary terms that carry the words they came from.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { day } from "../lib/dates";
import { useNotNow } from "../lib/not-now";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { Drawer } from "../ui/Drawer";
import { Pill } from "../ui/Pill";
import { Row } from "../ui/Row";
import { Skeleton } from "../ui/Skeleton";
import { ProposalEvidence, ProposalForms, ReachPicker, useProposal, type Proposal } from "./Learned";
import { useReadable } from "../lib/readable";
import { seenWords } from "../lib/knowledge";
import { RowMenu, type MenuAction } from "./RowMenu";
import styles from "./Learned.module.css";

import { EmptyState } from "../ui/EmptyState";
import { LoadFailed } from "../ui/LoadFailed";
import { useLoadFailure } from "../lib/load-failure";
import { refreshSince, writeMark } from "../lib/write";
type List = "daily" | "catch_up" | "people";

/** The kinds of queue line this draws: what was learned, the catch-up list, and the people offered to add. */
export function isLearned(line: S["QueueLineView"]): boolean {
  return line.kind === "learned" || line.kind === "catch_up" || line.kind === "people_offers";
}

/** One learned line of the Today queue. The counts come from the queue; the list loads when it is opened. */
export function LearnedLine(props: { line: S["QueueLineView"] }) {
  const { t, tn } = useWords();
  const { line } = props;
  const [open, setOpen] = useState(false);
  const notNow = useNotNow();
  const people = line.kind === "people_offers";
  const list: List = line.kind === "learned" ? "daily" : line.kind === "people_offers" ? "people" : "catch_up";
  const origins = line.origins ?? {};
  const sub = [
    line.kind === "learned" && origins.input ? tn("learned.today.from_inputs", origins.input) : "",
    line.kind === "learned" && origins.correction ? tn("learned.today.from_corrections", origins.correction) : "",
    line.kind === "learned" && line.expired ? tn("learned.today.expired", line.expired) : "",
    line.kind === "catch_up" && line.left_out ? tn("learned.today.left_out", line.left_out) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Row
      as="section"
      aria-label={people ? t("learned.today.people.label") : t("learned.today.label")}
      data-queue-line={line.kind}
      pill={<Pill tone="need">{people ? t("learned.today.people.label") : t("learned.today.label")}</Pill>}
      title={people ? tn("learned.today.people", line.count) : line.kind === "learned" ? tn("learned.today.review", line.count) : tn("learned.today.catch_up", line.count)}
      meta={sub || undefined}
      primary={
        <Button size="sm" variant="primary" data-key="primary" onClick={() => setOpen(true)}>
          {people ? t("learned.today.people.open") : t("learned.today.open")}
        </Button>
      }
      menu={people ? undefined : <RowMenu label={t("learned.today.label")} actions={[{ id: "not-now", label: t("queue.notnow"), run: () => notNow(line.key) }]} />}
    >
      {open && <ReviewDrawer list={list} onClose={() => setOpen(false)} />}
    </Row>
  );
}

/** The glossary terms a list holds that carry the words they came from: the only ones kept together. */
export function keptTogether(rows: Proposal[]): Proposal[] {
  return rows.filter((p) => p.kind === "glossary_entry" && !!p.evidence?.quote);
}

function ReviewDrawer(props: { list: List; onClose: () => void }) {
  const { t, tn } = useWords();
  const daily = props.list === "daily";
  const offers = props.list === "people";
  const proposals = useQuery({ queryKey: ["proposals"], queryFn: api.proposals, enabled: daily || offers });
  const catchUp = useQuery({ queryKey: ["catch-up"], queryFn: api.catchUp, enabled: !daily && !offers });
  const found = daily || offers ? proposals : catchUp;
  const failure = useLoadFailure(found);
  const rows = (daily ? proposals.data?.proposals : offers ? undefined : catchUp.data?.proposals) ?? [];
  const people = (offers ? proposals.data?.people : undefined) ?? [];
  const terms = keptTogether(rows);
  const title = offers ? t("learned.people.title") : daily ? t("learned.review.title") : t("learned.catch_up.title");
  const summary = offers
    ? []
    : daily
    ? [
        proposals.data?.origins.input ? tn("learned.today.from_inputs", proposals.data.origins.input) : "",
        proposals.data?.origins.correction ? tn("learned.today.from_corrections", proposals.data.origins.correction) : "",
        proposals.data?.expired ? tn("learned.today.expired", proposals.data.expired) : "",
      ]
    : [
        catchUp.data?.waiting ? tn("learned.catch_up.waiting", catchUp.data.waiting) : "",
        catchUp.data?.left_out ? tn("learned.catch_up.left_out", catchUp.data.left_out, { most: catchUp.data.most }) : "",
      ];
  return (
    <Drawer open title={title} onClose={props.onClose} wide>
      <div className={styles.review}>
        {summary.some(Boolean) && <p className={styles.summary}>{summary.filter(Boolean).join(" · ")}</p>}
        {terms.length > 0 && <KeepAll terms={terms} />}
        {failure.failed ? (
          <LoadFailed message={t("learned.load_failed")} onRetry={() => void found.refetch()} />
        ) : found.isPending ? (
          <Skeleton />
        ) : rows.length + people.length === 0 ? (
          <EmptyState text={t("learned.review.empty")} />
        ) : (
          <>
            {rows.some((p) => p.trust === "untrusted") && <p className={styles.summary}>{t("knowledge.outside")}</p>}
            <ul className={styles.list} aria-label={title}>
              {people.map((o) => (
                <PersonOfferRow key={o.id} offer={o} />
              ))}
              {rows.map((p) => (
                <ProposalRow key={p.id} p={p} />
              ))}
            </ul>
            {!offers && <p className={styles.summary}>{t("learned.review.one_at_a_time")}</p>}
          </>
        )}
      </div>
    </Drawer>
  );
}

/** Keeps every glossary term shown with the words it came from, each with its own Undo behind one toast. */
function KeepAll(props: { terms: Proposal[] }) {
  const { t, tn } = useWords();
  const act = useAct();
  const client = useQueryClient();
  const count = props.terms.length;
  const run = () =>
    void act(
      async () => {
        const done: string[] = [];
        const mark = writeMark();
        try {
          for (const p of props.terms) done.push((await api.keepKnowledge(p.id, { read_version: p.version })).changeset);
        } catch (err) {
          // A run that stopped part way still reads what the kept ones changed; one that finished is read by the action itself.
          if (done.length) void refreshSince(client, mark);
          throw err;
        }
        return done;
      },
      (done) => ({
        message: tn("toast.learned_kept_all", done.length),
        undo: async () => {
          for (const cs of done) await api.undo(cs);
        },
      }),
    );
  return (
    <div>
      <Button variant="primary" onClick={run}>
        {tn("learned.keep_all", count)}
      </Button>
      <p className={styles.summary}>{t("learned.keep_all_hint")}</p>
    </div>
  );
}

function ProposalRow(props: { p: Proposal }) {
  const { t, tn } = useWords();
  const { p } = props;
  const readable = useReadable();
  const state = useProposal(p);
  const menu: MenuAction[] = [
    { id: "just-this-time", label: t("learned.just_this_time"), run: () => void state.justThisTime() },
    { id: "edit", label: t("learned.edit"), run: () => state.setEditing(true) },
    { id: "discard", label: t("learned.discard"), run: () => state.setDiscarding(true) },
  ];
  const where = state.reachNow.charAt(0).toLowerCase() + state.reachNow.slice(1);
  const words = useWords();
  // One line says what it would mean and where it was seen, so Keep is a real choice.
  const means = p.kind === "glossary_entry" && p.term && p.meaning ? t("learned.means", { term: p.term, meaning: p.meaning }) : p.text;
  const meta = [seenWords({ activated: p.activated ?? null, messages: p.messages ?? 0 }, words), t("learned.applies", { where }), p.expires_at ? t("learned.expires", { date: day(p.expires_at) }) : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <Row
      data-learned={p.id}
      pill={<Pill>{t(p.learned_from === "person" ? "learned.from.person" : `learned.from.${p.came_from}`)}</Pill>}
      title={readable(means)}
      meta={meta}
      primary={
        <Button size="sm" variant="primary" onClick={() => void state.keep()}>
          {t("learned.keep")}
        </Button>
      }
      menu={<RowMenu label={readable(p.text)} actions={menu} />}
    >
      <div className={styles.detail}>
        {!state.editing && <ReachPicker choices={state.choices} value={state.chosen} onChange={state.setChosen} words={state.words} said={state.reachSaid} />}
        {!state.editing && <ProposalEvidence p={p} marked={false} />}
        {p.just_this_time_before > 0 && <p className={styles.summary}>{tn("learned.said_just_this_time", p.just_this_time_before)}</p>}
        <ProposalForms p={p} state={state} />
      </div>
    </Row>
  );
}

/** Someone the assistant offered to add: Keep puts them in People with the relation the offer gave and the sides their mail came from, in one change with Undo. */
function PersonOfferRow(props: { offer: S["PersonOfferView"] }) {
  const { t, tn } = useWords();
  const act = useAct();
  const { offer } = props;
  const keep = () =>
    void act(
      () => api.keepPerson(offer.id),
      (done) => ({ message: t("toast.person_kept", { name: offer.name }), undo: () => api.undo(done.changeset) }),
    );
  const leaveOut = () =>
    void act(
      () => api.leavePersonOut(offer.id),
      (done) => ({ message: t("toast.person_left_out", { name: offer.name }), undo: () => api.undo(done.changeset) }),
    );
  const sides = offer.sides ?? [];
  const meta = [
    offer.relation ? t("learned.person.relation", { relation: offer.relation }) : "",
    sides.length ? t("learned.person.on_sides", { sides: sides.join(", ") }) : "",
    tn("learned.person.messages", offer.count),
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Row
      data-person-offer={offer.id}
      pill={<Pill>{t("learned.person.pill")}</Pill>}
      title={offer.name}
      meta={meta}
      primary={
        <Button size="sm" variant="primary" onClick={keep}>
          {t("learned.person.keep")}
        </Button>
      }
      menu={<RowMenu label={offer.name} actions={[{ id: "not-this-one", label: t("learned.person.not_this_one"), run: leaveOut }]} />}
    >
      <div className={styles.detail}>
        <p className={styles.summary}>{offer.why}</p>
      </div>
    </Row>
  );
}
