import { describe, expect, it, vi } from "vitest";

import { SseHttpError, SseParser, streamEvents, type SseMessage } from "./sse";

describe("SseParser", () => {
  it("parses id, event and multi-line data, ignoring comments", () => {
    const parser = new SseParser();
    const messages = parser.feed(': ping\n\nid: 1\nevent: node.started\ndata: {"a":1}\ndata: {"b":2}\n\n');
    expect(messages).toEqual([{ id: "1", event: "node.started", data: '{"a":1}\n{"b":2}' }]);
  });

  it("handles chunks split anywhere, including inside CRLF", () => {
    const parser = new SseParser();
    const text = "id: 7\r\nevent: run.completed\r\ndata: done\r\n\r\n";
    const out: SseMessage[] = [];
    for (const ch of text) out.push(...parser.feed(ch));
    expect(out).toEqual([{ id: "7", event: "run.completed", data: "done" }]);
  });

  it("defaults the event name to message and keeps the last id", () => {
    const parser = new SseParser();
    expect(parser.feed("id: 3\ndata: x\n\ndata: y\n\n")).toEqual([
      { id: "3", event: "message", data: "x" },
      { id: "3", event: "message", data: "y" },
    ]);
  });

  it("drops a block with no data and supports a field without colon", () => {
    const parser = new SseParser();
    expect(parser.feed("event: lonely\n\ndata\n\n")).toEqual([{ id: null, event: "message", data: "" }]);
  });
});

function streamResponse(text: string, status = 200): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    }),
    { status, headers: { "Content-Type": "text/event-stream" } },
  );
}

describe("streamEvents", () => {
  it("reconnects with Last-Event-ID after a dropped connection and stops at the terminal event", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(streamResponse("id: 1\nevent: run.started\ndata: {}\n\n"))
      .mockResolvedValueOnce(streamResponse("id: 2\nevent: run.completed\ndata: {}\n\n"));
    const seen: string[] = [];
    await streamEvents({
      url: "/api/runs/x/events",
      headers: () => Promise.resolve({ Authorization: "Bearer t" }),
      signal: new AbortController().signal,
      onMessage: (m) => seen.push(m.event),
      isTerminal: (m) => m.event === "run.completed",
      retryDelayMs: 1,
      fetchImpl,
    });
    expect(seen).toEqual(["run.started", "run.completed"]);
    const second = fetchImpl.mock.calls[1]?.[1]?.headers as Record<string, string>;
    expect(second["Last-Event-ID"]).toBe("1");
    expect(second["Authorization"]).toBe("Bearer t");
  });

  it("refreshes once on 401 and does not retry other client errors", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(streamResponse("id: 1\nevent: run.completed\ndata: {}\n\n"));
    const onUnauthorized = vi.fn(() => Promise.resolve(true));
    await streamEvents({
      url: "/e",
      headers: () => Promise.resolve({}),
      signal: new AbortController().signal,
      onMessage: () => undefined,
      isTerminal: () => true,
      onUnauthorized,
      fetchImpl,
    });
    expect(onUnauthorized).toHaveBeenCalledOnce();

    const notFound = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 404 }));
    await expect(
      streamEvents({
        url: "/e",
        headers: () => Promise.resolve({}),
        signal: new AbortController().signal,
        onMessage: () => undefined,
        isTerminal: () => true,
        fetchImpl: notFound,
      }),
    ).rejects.toBeInstanceOf(SseHttpError);
    expect(notFound).toHaveBeenCalledOnce();
  });

  it("gives up after the retry budget on repeated network failures", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(
      streamEvents({
        url: "/e",
        headers: () => Promise.resolve({}),
        signal: new AbortController().signal,
        onMessage: () => undefined,
        isTerminal: () => true,
        maxRetries: 2,
        retryDelayMs: 1,
        fetchImpl,
      }),
    ).rejects.toBeInstanceOf(TypeError);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });
});
