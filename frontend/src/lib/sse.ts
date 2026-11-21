/**
 * Server-Sent Events over fetch (EventSource cannot send an Authorization header).
 * Implements the parts of the WHATWG event-stream format the API uses: `id`, `event`, `data`
 * (multi-line), comments and CR/LF/CRLF line endings. Reconnection resumes with Last-Event-ID.
 */

export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
}

/** Incremental parser: feed text chunks, get complete messages. */
export class SseParser {
  private buffer = "";
  private id: string | null = null;
  private event = "";
  private data: string[] = [];

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const messages: SseMessage[] = [];
    for (;;) {
      const match = /\r\n|\r|\n/.exec(this.buffer);
      if (!match) break;
      // A trailing CR may be the first half of CRLF: wait for the next chunk.
      if (match[0] === "\r" && match.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      const message = this.line(line);
      if (message) messages.push(message);
    }
    return messages;
  }

  private line(line: string): SseMessage | null {
    if (line === "") {
      if (this.data.length === 0) {
        this.event = "";
        return null;
      }
      const message = { id: this.id, event: this.event || "message", data: this.data.join("\n") };
      this.event = "";
      this.data = [];
      return message;
    }
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") this.data.push(value);
    else if (field === "event") this.event = value;
    else if (field === "id" && !value.includes("\0")) this.id = value;
    return null;
  }
}

export interface StreamOptions {
  url: string;
  headers: () => Promise<Record<string, string>>;
  signal: AbortSignal;
  onMessage: (message: SseMessage) => void;
  /** Stop when this returns true for a message (e.g. the terminal event). */
  isTerminal: (message: SseMessage) => boolean;
  maxRetries?: number;
  retryDelayMs?: number;
  fetchImpl?: typeof fetch;
  /** Called once on a 401; return true to retry with fresh headers (expired access token). */
  onUnauthorized?: () => Promise<boolean>;
}

export class SseHttpError extends Error {
  constructor(readonly status: number) {
    super(`event stream responded ${status}`);
    this.name = "SseHttpError";
  }
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason as Error);
      },
      { once: true },
    );
  });
}

/** Read the stream until the terminal event, reconnecting with Last-Event-ID on network drops. */
export async function streamEvents(options: StreamOptions): Promise<void> {
  const { maxRetries = 5, retryDelayMs = 1000, fetchImpl = fetch } = options;
  let lastId: string | null = null;
  let failures = 0;
  let reauthenticated = false;
  for (;;) {
    const headers: Record<string, string> = { Accept: "text/event-stream", ...(await options.headers()) };
    if (lastId !== null) headers["Last-Event-ID"] = lastId;
    try {
      const response = await fetchImpl(options.url, { headers, signal: options.signal });
      if (!response.ok || !response.body) throw new SseHttpError(response.status);
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      const parser = new SseParser();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const message of parser.feed(value)) {
          if (message.id !== null) lastId = message.id;
          failures = 0;
          options.onMessage(message);
          if (options.isTerminal(message)) {
            await reader.cancel();
            return;
          }
        }
      }
    } catch (error) {
      if (options.signal.aborted) throw error;
      if (
        error instanceof SseHttpError &&
        error.status === 401 &&
        !reauthenticated &&
        options.onUnauthorized
      ) {
        reauthenticated = true;
        if (await options.onUnauthorized()) continue;
      }
      // Client errors (auth, not found) will not fix themselves by retrying.
      if (error instanceof SseHttpError && error.status >= 400 && error.status < 500) throw error;
      failures += 1;
      if (failures > maxRetries) throw error;
    }
    await wait(retryDelayMs * failures, options.signal);
  }
}
