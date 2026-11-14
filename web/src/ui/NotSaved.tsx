// A save that failed (design 7.12, "States"): the row keeps what the person changed, says "Not saved" in words, an icon and the
// danger edge, gives the reason when there is one, and offers Try again. Nothing is lost: the screen holds the change until it
// saves. It is drawn inline where the change was made, never as a toast.
import { useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { useAllFailures, useFailedSaves, useFailureOf, type FailedSave } from "../lib/toasts";
import { useWords } from "../lib/wording";
import { Banner } from "./Banner";
import { Button } from "./Button";
import { StateMark } from "./StateMark";
import styles from "./NotSaved.module.css";

/** The plain reason a save failed, when the server gave one the person can read; empty otherwise. */
export function reasonOf(err: unknown): string {
  return err instanceof ApiError ? err.detail : "";
}

export function NotSaved(props: {
  /** What was being saved, in the person's words ("Pay the deposit"); left out, the line says "That". */
  what?: string;
  /** Why, when it is known. */
  reason?: string;
  onRetry: () => void;
  busy?: boolean;
  /** The page's banner says this save in words and holds Try again, so the line under the row is only the "Not saved" mark. */
  inBanner?: boolean;
  className?: string;
}) {
  const { t } = useWords();
  const reason = (props.reason ?? "").trim();
  // The page's banner says it once in words, with the one Try again; the row keeps only the short mark (icon and words).
  if (props.inBanner) {
    return (
      <div className={[styles.mark, props.className ?? ""].filter(Boolean).join(" ")} role="alert" data-not-saved="">
        <StateMark tone="danger">{t("state.not_saved")}</StateMark>
      </div>
    );
  }
  return (
    <div className={[styles.row, props.className ?? ""].filter(Boolean).join(" ")} role="alert" data-not-saved="">
      <StateMark tone="danger">{t("state.not_saved")}</StateMark>
      <p className={styles.text}>
        {props.what ? t("state.not_saved.what", { what: props.what }) : t("state.not_saved.that")} {reason && `${reason} `}
        {t("state.not_saved.kept")}
      </p>
      <Button size="sm" icon="refresh" loading={props.busy} onClick={props.onRetry}>
        {t("action.try_again")}
      </Button>
    </div>
  );
}

/** The failed save held for one thing (`failedId`, the key its action named), drawn where that thing is: nothing when it saved. */
export function FailedSaveLine(props: { failedId: string; className?: string; /** Drawn as a list item of its own, under the row it is for, in a list that is not made of Rows. */ asItem?: boolean }) {
  const failure = useFailureOf(props.failedId);
  const { register } = useFailedSaves();
  // While this line is on screen a failed save for its key can be shown here; off screen, the save toasts instead.
  useEffect(() => register(props.failedId), [register, props.failedId]);
  const [busy, setBusy] = useState(false);
  if (!failure) return null;
  const line = (
    <NotSaved
      className={props.asItem ? undefined : props.className}
      what={failure.what}
      reason={failure.reason}
      busy={busy}
      inBanner
      onRetry={() => {
        setBusy(true);
        void Promise.resolve(failure.retry()).finally(() => setBusy(false));
      }}
    />
  );
  return props.asItem ? <li className={props.className}>{line}</li> : line;
}

function FailureBanner(props: { failure: FailedSave }) {
  const { t } = useWords();
  const [busy, setBusy] = useState(false);
  const { failure } = props;
  return (
    <Banner
      role="alert"
      tone="danger"
      data-not-saved-banner=""
      action={
        <Button
          size="sm"
          icon="refresh"
          loading={busy}
          onClick={() => {
            setBusy(true);
            void Promise.resolve(failure.retry()).finally(() => setBusy(false));
          }}
        >
          {t("action.try_again")}
        </Button>
      }
    >
      {failure.what ? t("state.not_saved.what", { what: failure.what }) : t("state.not_saved.that")} {failure.reason && `${failure.reason} `}
      {t("state.not_saved.kept")}
    </Banner>
  );
}

/** The saves that failed, as banners for the page's banner slot: each names the thing and has the one Try again, while the row it
 * was made on keeps its not-done state and its own note. */
export function FailureBanners() {
  const all = useAllFailures();
  return (
    <>
      {Object.entries(all).map(([key, failure]) => (
        <FailureBanner key={key} failure={failure} />
      ))}
    </>
  );
}
