// Today's lines for an account that is not being read (design 7.7): "<name>'s mail isn't being read · since 4:20 PM", with the one
// button that fixes it. They come first in At risk and count among the things that need the person. The name is the side the
// account serves, as the calendar's banner and the header's chip name it; the address is on Connections only.
import { sidesOfAccount, unreadParts } from "../lib/account-today";
import type { AccountState } from "../lib/connections";
import { whenWords } from "../lib/coverage";
import { useSideFilter } from "../lib/sides";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { Row } from "../ui/Row";
import { FilledPrimary } from "../ui/rowContext";
import { accountName } from "../lib/account-name";
import { useSignInAgain } from "./AccountRow";
import styles from "./Today.module.css";

function AccountTodayRow(props: { account: AccountState; first: boolean; filled: boolean; everySide: boolean; onOpenConnections: () => void }) {
  const { t } = useWords();
  const { account } = props;
  const again = useSignInAgain(account);
  const options = useSideFilter().options;
  const sides = sidesOfAccount(account);
  const name = accountName(account, (id) => options.find((o) => o.id === id)?.name, t("account_today.fallback"));
  const what = t(`account_today.${unreadParts(account)}`, { name });
  const since = account.since ?? account.latest;
  const title = since ? t("account_today.since", { what, when: whenWords(since, new Date(), t) }) : what;
  const signIn = again.item !== undefined && account.need !== null;
  return (
    <FilledPrimary.Provider value={props.filled}>
    <Row
      lead={<Icon name="alert" />}
      state={props.first ? "danger" : undefined}
      aria-label={title}
      role="group"
      data-account-line={account.key}
      title={
        <>
          <span>{title}</span>
          {/* Under one side's filter, an account that serves no side says so, so it is never read as that side's. */}
          {props.everySide && sides.length === 0 && (
            <span className={styles.tag} data-every-side="">
              {t("queue.every_side")}
            </span>
          )}
        </>
      }
      oneLine
      primary={
        signIn ? (
          <Button size="sm" variant={props.filled ? "primary" : "secondary"} data-key="primary" disabled={again.busy || !again.item?.ready} aria-label={t("sign_in.sign_in_again_named", { label: name })} onClick={() => void again.start()}>
            {t("account.sign_in_again")}
          </Button>
        ) : (
          <Button size="sm" variant={props.filled ? "primary" : "secondary"} data-key="primary" onClick={props.onOpenConnections}>
            {t("account_today.open")}
          </Button>
        )
      }
    />
    </FilledPrimary.Provider>
  );
}

export function AccountTodayRows(props: { accounts: AccountState[]; /** The first account carries the screen's one filled button. */ filled?: boolean; everySide: boolean; onOpenConnections: () => void }) {
  return (
    <>
      {props.accounts.map((account, i) => (
        <AccountTodayRow key={account.key} account={account} first={i === 0} filled={!!props.filled && i === 0} everySide={props.everySide} onOpenConnections={props.onOpenConnections} />
      ))}
    </>
  );
}
