export type SSECard = { kind: "order" | "logistics" | "refund"; data: any };
export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  cards?: SSECard[];
  /** 该条 assistant 回答是否失败（onError 时置 true，用于显示重试按钮） */
  failed?: boolean;
  /** 失败时记录对应的用户消息文本，供重试时重新发送 */
  retryText?: string;
  /** 该条 assistant 回答是否触发转人工（human_handoff 事件后置 true，用于显示转人工按钮） */
  handoff?: boolean;
  /** 该条消息是否由人工客服回复（转人工流程中追加） */
  human?: boolean;
};

// 服务间认证 Key：开发环境默认 dev-local-key；生产必须显式配置 NEXT_PUBLIC_API_KEY
// （构建期内联），未配置时置空——请求带空 Key 会被后端 401，避免静默用弱默认值上线
const API_KEY =
  process.env.NEXT_PUBLIC_API_KEY ||
  (process.env.NODE_ENV === "development" ? "dev-local-key" : "");

// 区分“用户主动取消”（AbortError）与真实异常：主动取消不展示错误提示
function isAbortError(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { name?: string }).name === "AbortError";
}

export type HistoryItem = { role: "user" | "assistant"; content: string };

// 送入后端的对话历史条数上限（与后端 MAX_HISTORY 一致，双保险）
export const MAX_HISTORY = 8;

export async function streamChat(
  sessionId: string,
  message: string,
  history: HistoryItem[],
  handlers: {
    onThinking: (s: string) => void;
    onToken: (t: string) => void;
    onCard: (c: SSECard) => void;
    onSources: (items: { title: string; category: string }[]) => void;
    /** 收到 human_handoff 事件时回调；可选以兼容仅做事件解析的调用方 */
    onHandoff?: () => void;
    onDone: () => void;
    onError: (msg: string) => void;
  }
): Promise<{ cancel: () => void }> {
  const controller = new AbortController();
  const signal = controller.signal;

  // 传输层再截断一次：调用方可能直接传入超长 history（双保险，与 ChatWindow/后端一致）
  const hist = history.slice(-MAX_HISTORY);

  // 流式逻辑在后台异步执行；外层立刻返回 { cancel }，调用方无需等流结束即可拿到取消句柄
  (async () => {
    let resp: Response;
    try {
      resp = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({ session_id: sessionId, message, history: hist }),
        signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    } catch (e) {
      if (isAbortError(e)) {
        handlers.onDone(); // 主动取消：静默收尾，不展示错误
        return;
      }
      handlers.onError("服务暂时不可用，请稍后重试");
      handlers.onDone();
      return;
    }
    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let evt: any;
          try {
            evt = JSON.parse(line.slice(6));
          } catch {
            continue; // 畸形帧跳过
          }
          if (evt.type === "thinking") handlers.onThinking(evt.status);
          else if (evt.type === "token") {
            handlers.onToken(evt.text);
            // 关键：让出事件循环让浏览器逐字 paint。
            // 本地/缓冲环境下一次 reader.read() 会返回多个 token 帧，若在同一 JS 任务内连续
            // 处理完所有 token，浏览器只在任务结束后绘制一次 → 回答"一次性蹦出"。
            // 每帧 await ~16ms（≈60fps），给浏览器在 token 之间绘制的时间点，形成打字效果。
            await new Promise((r) => setTimeout(r, 16));
          }
          else if (evt.type === "card") handlers.onCard({ kind: evt.kind, data: evt.data });
          else if (evt.type === "sources") handlers.onSources(evt.items);
          else if (evt.type === "human_handoff") handlers.onHandoff?.();
          else if (evt.type === "error") handlers.onError(evt.message ?? "服务异常");
          else if (evt.type === "done") handlers.onDone();
        }
      }
    } catch (e) {
      if (isAbortError(e)) {
        handlers.onDone(); // 主动取消：静默收尾，不展示错误
        return;
      }
      handlers.onError("连接中断，请稍后重试");
      handlers.onDone();
    }
  })();

  return { cancel: () => controller.abort() };
}
