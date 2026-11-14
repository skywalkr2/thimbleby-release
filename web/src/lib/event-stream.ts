// The server's live stream, read with the session as a header. The browser's own EventSource can't send one, and the
// session is never a cookie, so this reads the stream with `fetch` and keeps the parts of EventSource the app uses:
// named events, `onerror`, `readyState` (0 while it retries, 2 once closed) and `close`. Like EventSource it retries
// after the stream drops; unlike it, a refused sign-in closes it for good.
import { authHeaders, sessionReady } from "./session";

const RETRY_MS = 3000;

export class AuthEventSource {
  readyState = 0;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Array<(event: { data: string }) => void>>();
  private stop = new AbortController();
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly url: string) {
    void this.run();
  }

  addEventListener(name: string, fn: (event: { data: string }) => void): void {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), fn]);
  }

  close(): void {
    this.readyState = 2;
    this.stop.abort();
    if (this.timer) clearTimeout(this.timer);
  }

  private emit(name: string, data: string): void {
    for (const fn of this.listeners.get(name) ?? []) fn({ data });
  }

  private async run(): Promise<void> {
    await sessionReady();
    while (this.readyState !== 2) {
      try {
        const response = await fetch(this.url, { headers: { ...authHeaders(), accept: "text/event-stream" }, signal: this.stop.signal });
        if (response.status === 401 || response.status === 403) {
          this.close();
          this.onerror?.();
          return;
        }
        if (!response.ok || !response.body) throw new Error(String(response.status));
        this.readyState = 1;
        await this.read(response.body);
      } catch {
        if (this.readyState === 2) return;
      }
      this.readyState = 0;
      this.onerror?.();
      await new Promise<void>((resolve) => {
        this.timer = setTimeout(resolve, RETRY_MS);
      });
    }
  }

  private async read(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      let end = buffer.indexOf("\n\n");
      while (end !== -1) {
        this.dispatch(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        end = buffer.indexOf("\n\n");
      }
    }
  }

  private dispatch(block: string): void {
    let name = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      const text = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "event") name = text;
      else if (field === "data") data.push(text);
    }
    if (data.length > 0 || name !== "message") this.emit(name, data.join("\n"));
  }
}
