// One way for any screen to open Report a problem with starting words in it (a line that drafts a report for the
// makers). The shell provides it when reporting is on; without it a screen has no form to open and keeps its own way.
import { createContext, useContext } from "react";

/** Opens the report form with these words filled in; the person reads them, changes them and presses Send. */
export type OpenReport = (words: string) => void;

const OpenReportContext = createContext<OpenReport | undefined>(undefined);

export const OpenReportProvider = OpenReportContext.Provider;

/** The opener, or undefined when the shell offers no report form. */
export function useOpenReport(): OpenReport | undefined {
  return useContext(OpenReportContext);
}
