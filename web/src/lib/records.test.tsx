import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { useDetailLines } from "./records";
import { WordingProvider } from "./wording";

const wrapper = ({ children }: { children: ReactNode }) => <WordingProvider>{children}</WordingProvider>;

test("a detail that is a whole web address is a link said by what it opens, never the long address", () => {
  const lines = renderHook(() => useDetailLines(), { wrapper }).result.current;
  const address = ["https:", "", "mail.example.com", "mail", "?authuser=1"].join("/");
  expect(lines("link", address, undefined, new Map())).toEqual([{ label: "Open the original", url: address }]);
  // Words that only mention an address stay words.
  const sentence = `See ahead ${address} for more`;
  expect(lines("notes", sentence, undefined, new Map())).toEqual([sentence]);
});
