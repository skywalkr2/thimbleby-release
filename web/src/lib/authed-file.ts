// Files and pictures the server keeps behind the session. A plain link or picture address carries no header, so these
// fetch the bytes with the session and hand the browser a local address for them.
import { useEffect, useState } from "react";
import { openKeptFile } from "./external-links";
import { authHeaders, sessionReady } from "./session";

/** The bytes at an app address (relative, such as `api/files/x/content`), fetched with the session. */
export async function fetchBlob(path: string): Promise<Blob> {
  await sessionReady();
  const response = await fetch(path, { headers: authHeaders() });
  if (!response.ok) throw new Error(String(response.status));
  return response.blob();
}

/** A local address for a picture the server keeps: `undefined` until it has arrived, `null` when it can't be had. */
export function useBlobUrl(path: string): string | null | undefined {
  const [url, setUrl] = useState<{ path: string; value: string | null } | null>(null);
  useEffect(() => {
    let made: string | null = null;
    let live = true;
    fetchBlob(path).then(
      (blob) => {
        if (!live) return;
        made = URL.createObjectURL(blob);
        setUrl({ path, value: made });
      },
      () => live && setUrl({ path, value: null }),
    );
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [path]);
  return url?.path === path ? url.value : undefined;
}

const KEPT = /(?:^|\/)api\/files\/([^/]+)\/content$/;

/** A click handler for a link to a file. In the installed app's window the computer's own program for the file opens it
 *  (the window ignores downloads and pop-ups); in a browser, pictures open in a new tab and anything else is saved under
 *  its own name. The server
 *  sends only pictures as pictures, so nothing here ever opens as a page. The link's own address stays in the
 *  link, for copying. */
export function openFile(path: string, name: string, picture: boolean) {
  return (event: { preventDefault: () => void }) => {
    event.preventDefault();
    const kept = KEPT.exec(path)?.[1];
    if (kept && openKeptFile(decodeURIComponent(kept))) return;
    // A window opened after the wait would be taken for a pop-up, so it opens from the click and is pointed afterwards.
    const win = picture ? window.open("", "_blank") : null;
    if (win) win.opener = null;
    fetchBlob(path).then(
      (blob) => {
        const url = URL.createObjectURL(blob);
        if (win) win.location.href = url;
        else {
          const link = document.createElement("a");
          link.href = url;
          link.download = name;
          link.click();
        }
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      },
      () => win?.close(),
    );
  };
}
