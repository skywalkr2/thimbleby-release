// Notices that something needs the person (design 7.19): the ways of getting one, each with "Send me a test". The browser
// needs its own permission, asked for only from a button here. A chat app or push topic is the person's own address, kept
// on this computer like a key, and the app it belongs to is picked by name from a list (the app's own, and the person's) with
// one line on where to find the address in it. Mail to themselves is listed once an account that can send mail has acting turned
// on and the person has an address of their own: they pick the account and the address from lists, see the exact notice, and
// say yes once; it then goes without asking each time, to that address only.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { api, ApiError } from "../lib/api";
import { askNotify, notifyState, showNotification, type NotifyState } from "../lib/notify";
import { problemText } from "../lib/problem";
import { inOrder, useAfterSave, useFreshFingerprint } from "../lib/settings-save";
import { useToasts } from "../lib/toasts";
import { useWords } from "../lib/wording";
import { heldOf, KeptSecretRow } from "./KeptSecrets";
import styles from "./Notifications.module.css";
import { Button } from "../ui/Button";
import { Select } from "../ui/Select";
import { FormField } from "../ui/FormField";
import { StateMark } from "../ui/StateMark";
/** One target's test: runs it, and says how it went in a toast, or in the card when it didn't work. */
function useTest(target: "browser" | "webhook") {
  const { t } = useWords();
  const { push } = useToasts();
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    setProblem("");
    try {
      const answer = await api.testNotify(target);
      if (!answer.ok) {
        setProblem(answer.problem ?? t("notices.test_failed"));
        return;
      }
      if (target === "browser") {
        if (notifyState() !== "granted") {
          setProblem(t("notices.browser.allow_first"));
          return;
        }
        showNotification(answer.message, undefined, "notices-test");
      }
      push({ message: t(target === "browser" ? "notices.test_shown" : "notices.test_sent") });
    } catch (err) {
      setProblem(err instanceof ApiError && err.detail ? err.detail : problemText(err, t));
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, problem };
}

function BrowserTarget() {
  const { t } = useWords();
  const [state, setState] = useState<NotifyState>(notifyState);
  const test = useTest("browser");
  const base = useId();
  return (
    <li className={styles.target} aria-labelledby={`${base}-name`}>
      <h4 id={`${base}-name`}>{t("notices.browser.title")}</h4>
      <p>{t("notices.browser.hint")}</p>
      {state === "granted" && (
        <p role="status">
          <StateMark tone="ok">{t("notify.granted")}</StateMark>
        </p>
      )}
      {state === "denied" && (
        <>
          <p role="status">
            <StateMark tone="warn">{t("notify.denied")}</StateMark>
          </p>
          <p className="hint">{t("notify.denied_how")}</p>
        </>
      )}
      {state === "unsupported" && (
        <p role="status">
          <StateMark tone="neutral">{t("notify.unsupported")}</StateMark>
        </p>
      )}
      {test.problem && (
        <p className="problem-note" role="alert">
          {test.problem}
        </p>
      )}
      <div className={styles.actions}>
        {state === "default" && (
          <Button variant="primary" size="sm" onClick={() => void askNotify().then(setState)}>
            {t("notify.allow")}
          </Button>
        )}
        {state === "denied" && (
          <Button size="sm" onClick={() => setState(notifyState())}>
            {t("notify.check_again")}
          </Button>
        )}
        {state === "granted" && (
          <Button size="sm" disabled={test.busy} onClick={() => void test.run()}>
            {t("notices.test")}
          </Button>
        )}
      </div>
    </li>
  );
}

function WebhookTarget(props: { local: boolean }) {
  const { t } = useWords();
  const afterSave = useAfterSave();
  const fingerprint = useFreshFingerprint();
  const view = useQuery({ queryKey: ["notifications"], queryFn: api.notifications });
  const test = useTest("webhook");
  const base = useId();
  const held = view.data ? heldOf(view.data.webhook) : null;
  const testButton = held ? (
    <Button size="sm" disabled={test.busy} onClick={() => void test.run()}>
      {t("notices.test")}
    </Button>
  ) : null;
  const apps = view.data?.apps ?? [];
  const chosen = apps.find((a) => a.id === view.data?.app);
  return (
    <li className={styles.target} aria-labelledby={`${base}-name`}>
      <h4 id={`${base}-name`}>{t("notices.webhook.title")}</h4>
      <p>{t("notices.webhook.hint")}</p>
      {apps.length > 0 && (
        <FormField id={`${base}-app`} label={t("notices.app.label")}>
          <Select
            id={`${base}-app`}
            value={chosen?.id ?? ""}
            aria-describedby={chosen ? `${base}-app-where` : undefined}
            onChange={(e) =>
              void (async (app: string) => {
                const saved = await inOrder(async () => api.setNotifyApp({ app, fingerprint: await fingerprint() }));
                await afterSave(saved, { message: t("notices.app.saved") });
              })(e.target.value)
            }
          >
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
          {chosen && (
            <p className="hint" id={`${base}-app-where`}>
              {t("notices.app.where", { where: chosen.where })}
            </p>
          )}
        </FormField>
      )}
      <KeptSecretRow
        id={`${base}-address`}
        label={t("notices.webhook.label")}
        saveLabel={t("notices.webhook.save")}
        local={props.local}
        held={held}
        hint={t("notices.webhook.kept")}
        onSave={async (body) => {
          const saved = await inOrder(async () => api.setNotifyWebhook({ ...body, fingerprint: await fingerprint() }));
          await afterSave(saved, { message: t("notices.webhook.saved") });
        }}
        more={testButton}
        whenHeld={testButton}
      />
      {(test.problem || view.data?.problem) && (
        <p className="problem-note" role="alert">
          {test.problem || view.data?.problem}
        </p>
      )}
    </li>
  );
}

/** Mail to the person themselves: pick the account and one of their own addresses, read the exact notice, say yes once.
 * It stays off, and the card says nothing of it, until an account can send mail and the person has an address. */
function MailTarget() {
  const { t } = useWords();
  const { push } = useToasts();
  const client = useQueryClient();
  const card = useQuery({ queryKey: ["notifications", "mail"], queryFn: api.noticeMail });
  const base = useId();
  const [account, setAccount] = useState("");
  const [address, setAddress] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const data = card.data;
  if (!data) return null;
  const standing = data.standing;
  const stale = standing?.stale ?? [];
  if (!standing && (data.accounts.length === 0 || data.addresses.length === 0)) return null;
  const chosenAccount = account || standing?.account || data.accounts[0]?.id || "";
  const chosenAddress = address || standing?.address || data.addresses[0] || "";
  const refresh = () => client.invalidateQueries({ queryKey: ["notifications"] });
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setProblem("");
    try {
      await work();
      await refresh();
    } catch (err) {
      setProblem(err instanceof ApiError && err.detail ? err.detail : problemText(err, t));
    } finally {
      setBusy(false);
    }
  };
  const shown = data.titles ?? data.count;
  return (
    <li className={styles.target} aria-labelledby={`${base}-name`}>
      <h4 id={`${base}-name`}>{t("notices.mail.title")}</h4>
      <p>{t("notices.mail.hint")}</p>
      <FormField id={`${base}-account`} label={t("notices.mail.account")}>
        <Select id={`${base}-account`} value={chosenAccount} onChange={(e) => setAccount(e.target.value)}>
          {data.accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
          {standing && !data.accounts.some((a) => a.id === standing.account) && (
            <option value={standing.account}>{standing.account_label ?? standing.account}</option>
          )}
        </Select>
      </FormField>
      <FormField id={`${base}-address`} label={t("notices.mail.address")}>
        <Select id={`${base}-address`} value={chosenAddress} onChange={(e) => setAddress(e.target.value)}>
          {data.addresses.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </Select>
      </FormField>
      <p className="hint">{data.titles ? t("notices.mail.with_titles") : t("notices.mail.count_only")}</p>
      <div role="group" aria-label={t("notices.mail.example")}>
        <p>
          <strong>{shown.subject}</strong>
        </p>
        <pre>{shown.body}</pre>
      </div>
      {standing && (
        <p role="status">
          <StateMark tone={stale.length ? "warn" : "ok"}>
            {stale.length ? t("notices.mail.stale") : t("notices.mail.on", { address: standing.address })}
          </StateMark>
        </p>
      )}
      {problem && (
        <p className="problem-note" role="alert">
          {problem}
        </p>
      )}
      <div className={styles.actions}>
        <Button
          variant="primary"
          size="sm"
          disabled={busy || !chosenAccount || !chosenAddress}
          onClick={() =>
            void run(async () => {
              await api.giveNoticeMail({ account: chosenAccount, address: chosenAddress, template_version: data.template_version });
              push({ message: t("notices.mail.saved") });
            })
          }
        >
          {standing ? t("notices.mail.change") : t("notices.mail.give")}
        </Button>
        {standing && (
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api.endNoticeMail();
                push({ message: t("notices.mail.ended") });
              })
            }
          >
            {t("notices.mail.end")}
          </Button>
        )}
        {standing && (
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const answer = await api.testNoticeMail();
                if (!answer.ok) throw new ApiError(409, answer.problem ?? t("notices.test_failed"));
                push({ message: t("notices.mail.test_sent", { address: standing.address }) });
              })
            }
          >
            {t("notices.test")}
          </Button>
        )}
      </div>
    </li>
  );
}

/** The ways of getting a notice, under the settings that turn notices on. `part` shows only the browser's way (on the
 * Notices page) or only the person's own chat or phone app (behind Advanced); left out, both. */
export function Notifications(props: { part?: "browser" | "webhook" }) {
  const { t } = useWords();
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup });
  const view = useQuery({ queryKey: ["notifications"], queryFn: api.notifications });
  const base = useId();
  if (props.part === "webhook") {
    return (
      <section className="notice-targets" aria-labelledby={`${base}-title`}>
        <h4 id={`${base}-title`}>{t("notices.advanced")}</h4>
        <ul className={styles.targets}>
          <WebhookTarget local={setup.data?.local ?? true} />
        </ul>
      </section>
    );
  }
  return (
    <section className="notice-targets" aria-labelledby={`${base}-title`}>
      <h3 id={`${base}-title`}>{t("notices.title")}</h3>
      <p className="hint">{t("notices.intro")}</p>
      {view.data && !view.data.enabled && <p className="hint">{t("notices.off")}</p>}
      <ul className={styles.targets}>
        <BrowserTarget />
        <MailTarget />
        {props.part === undefined && (
          <li className={styles.target}>
            <details className="more-options advanced">
              <summary>{t("notices.advanced")}</summary>
              <ul className={styles.targets}>
                <WebhookTarget local={setup.data?.local ?? true} />
              </ul>
            </details>
          </li>
        )}
      </ul>
    </section>
  );
}
