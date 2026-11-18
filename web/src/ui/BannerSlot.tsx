// The banner slot (design 7.12, "States"): where a screen's banners live, one place below the title and above the tabs, so a banner
// that comes (the app offline, an account that can't be read) never moves the title. The screen's header draws the slot (PageHeader),
// the offline banner first and then the screen's own banners in the order given. A screen without a header gets the offline banner
// at the top of the page (`BannerFallback`) until a header takes it over (`useClaimBanners`).
import { createContext, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { FailureBanners } from "./NotSaved";
import { OfflineBanner } from "./OfflineBanner";
import { UpdateReadyBanner } from "./UpdateReadyBanner";

const Claim = createContext<() => () => void>(() => () => undefined);
const Claimed = createContext(false);

/** Wraps the page body: it knows whether a header has taken the offline banner into its own slot. */
export function BannerHome(props: { children: ReactNode }) {
  const [n, setN] = useState(0);
  const claim = useMemo(
    () => () => {
      setN((c) => c + 1);
      return () => setN((c) => c - 1);
    },
    [],
  );
  return (
    <Claim.Provider value={claim}>
      <Claimed.Provider value={n > 0}>{props.children}</Claimed.Provider>
    </Claim.Provider>
  );
}

/** A header that draws the banner slot calls this, so the page-level offline banner steps aside before it is painted. */
export function useClaimBanners(draws: boolean): void {
  const claim = useContext(Claim);
  useLayoutEffect(() => (draws ? claim() : undefined), [claim, draws]);
}

/** The offline banner at the top of a page whose screen draws no header slot of its own. */
export function BannerFallback() {
  return useContext(Claimed) ? null : (
    <>
      <OfflineBanner />
      <UpdateReadyBanner />
      <FailureBanners />
    </>
  );
}

/** The slot a header draws: the offline banner, then the screen's own banners. Empty, it takes no room. */
export function BannerSlot(props: { className?: string; children?: ReactNode }) {
  return (
    <div className={props.className} data-banner-slot="">
      <OfflineBanner />
      <UpdateReadyBanner />
      <FailureBanners />
      {props.children}
    </div>
  );
}
