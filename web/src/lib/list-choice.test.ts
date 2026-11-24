import { act, renderHook } from "@testing-library/react";
import { expect, test } from "vitest";
import { useListChoice } from "./list-choice";

test("a row that leaves the list is replaced by its neighbor where the pane has room, and by nothing where it would cover the list", () => {
  for (const [wait, after] of [[false, "b"], [true, null]] as const) {
    const { result, rerender } = renderHook(({ keys }) => useListChoice({ keys, beside: true, first: null, wait }), { initialProps: { keys: ["a", "b", "c"] } });
    act(() => result.current.choose("a"));
    rerender({ keys: ["b", "c"] });
    expect(result.current.chosen, `wait ${wait}`).toBe(after);
  }
});
