// The brand moment of the setup's first and last screens (design 7.8, 7.12): the product's mark in its day or night version, with
// the star beneath it. It is decoration, so it says nothing to a screen reader.
import markDay from "../assets/brand/mark-day.svg?inline";
import markNight from "../assets/brand/mark-night.svg?inline";
import { useWords } from "../lib/wording";
import styles from "./SetupBrand.module.css";

export function SetupBrand() {
  return (
    <div className={styles.brand} data-setup-brand="" aria-hidden="true">
      <img className={`${styles.mark} ${styles.markDay}`} src={markDay} alt="" data-brand-mark="day" />
      <img className={`${styles.mark} ${styles.markNight}`} src={markNight} alt="" data-brand-mark="night" />
      <span className={styles.glyph} data-brand-glyph="">
        ✳
      </span>
    </div>
  );
}

/** The product's mark and name at the left of setup's header, as the header of every other screen has them (not a link: the person is in setup). */
export function SetupHeaderBrand() {
  const { t } = useWords();
  return (
    <span className={styles.headBrand} data-setup-header-brand="">
      <img className={`${styles.headMark} ${styles.markDay}`} src={markDay} alt="" data-brand-mark="day" />
      <img className={`${styles.headMark} ${styles.markNight}`} src={markNight} alt="" data-brand-mark="night" />
      <span className={styles.headName}>{t("app.name")}</span>
    </span>
  );
}
