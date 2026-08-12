import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChat } from "@/lib/sse";

// 构造 SSE 响应体：把每段文本按 TextEncoder 编码成 ReadableStream 的分块。
function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

function makeHandlers() {
  return {
    onThinking: vi.fn(),
    onToken: vi.fn(),
    onCard: vi.fn(),
    onSources: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
  };
}

describe("streamChat", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("按序解析 thinking/token/card/sources/done 事件", async () => {
    const chunks = [
      'data: {"type":"thinking","status":"正在识别问题"}\n',
      'data: {"type":"token","text":"您"}\n',
      'data: {"type":"token","text":"好"}\n',
      'data: {"type":"card","kind":"order","data":{"order_id":"O123","status":"已发货","items":"手机x1","amount":3999}}\n',
      'data: {"type":"sources","items":[{"title":"售后政策","category":"refund"}]}\n',
      'data: {"type":"done"}\n',
    ];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: sseStream(chunks) });
    vi.stubGlobal("fetch", fetchMock);

    const h = makeHandlers();
    await streamChat("s1", "hi", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onThinking).toHaveBeenCalledWith("正在识别问题");
    expect(h.onToken).toHaveBeenNthCalledWith(1, "您");
    expect(h.onToken).toHaveBeenNthCalledWith(2, "好");
    expect(h.onCard).toHaveBeenCalledWith({
      kind: "order",
      data: { order_id: "O123", status: "已发货", items: "手机x1", amount: 3999 },
    });
    expect(h.onSources).toHaveBeenCalledWith([{ title: "售后政策", category: "refund" }]);
    expect(h.onError).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/chat", expect.objectContaining({ method: "POST" }));
  });

  it("畸形帧与非 data: 行被跳过，不崩溃", async () => {
    const chunks = [
      'data: not-json\n',
      'ping: heartbeat\n',
      'data: {"type":"token","text":"有效"}\n',
      '\n',
      'data: {"type":"done"}\n',
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body: sseStream(chunks) }));

    const h = makeHandlers();
    await streamChat("s1", "hi", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onToken).toHaveBeenCalledTimes(1);
    expect(h.onToken).toHaveBeenCalledWith("有效");
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("HTTP 非 2xx 时触发 onError 并收尾", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));

    const h = makeHandlers();
    await streamChat("s1", "hi", h);
    await vi.waitFor(() => expect(h.onError).toHaveBeenCalled());

    expect(h.onError).toHaveBeenCalledWith("服务暂时不可用，请稍后重试");
    expect(h.onDone).toHaveBeenCalled();
  });

  it("cancel() 可中断永不结束的流且不触发 onError（AbortError 路径）", async () => {
    // 返回一个永不结束的流；当 AbortController 的 signal 触发 abort 时，把流以 AbortError 报错，
    // 模拟真实 fetch/ReadableStream 在取消时的行为，从而走到 streamChat 的 AbortError 分支。
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: unknown, init: { signal?: AbortSignal }) => {
        const signal = init?.signal;
        const stream = new ReadableStream({
          start(controller) {
            signal?.addEventListener("abort", () => {
              controller.error(new DOMException("The operation was aborted.", "AbortError"));
            });
          },
        });
        return Promise.resolve({ ok: true, body: stream });
      })
    );

    const h = makeHandlers();
    const p = streamChat("s1", "hi", h);
    const { cancel } = await p;
    cancel();
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onError).not.toHaveBeenCalled();
  });
});
