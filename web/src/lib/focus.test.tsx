import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useFirstField } from "./focus";

function Form() {
  const ref = useFirstField<HTMLFormElement>();
  return (
    <form ref={ref}>
      <input aria-label="Name" />
      <input aria-label="Folder" />
    </form>
  );
}

afterEach(() => vi.restoreAllMocks());

test("a form's first field gets the cursor a frame after it opens", () => {
  const frames: FrameRequestCallback[] = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => frames.push(cb));
  render(<Form />);
  frames.forEach((cb) => cb(0));
  expect(screen.getByLabelText("Name")).toHaveFocus();
});

test("a late frame never takes the cursor from a field the person already went to (H5-16's cause)", () => {
  const frames: FrameRequestCallback[] = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => frames.push(cb));
  render(<Form />);
  screen.getByLabelText("Folder").focus();
  frames.forEach((cb) => cb(0));
  expect(screen.getByLabelText("Folder")).toHaveFocus();
});
