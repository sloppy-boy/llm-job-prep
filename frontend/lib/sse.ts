export type SSECard = { kind: "order" | "logistics" | "refund"; data: any };
export type ChatMessage = { role: "user" | "assistant"; content: string; cards?: SSECard[] };

export async function streamChat(
  sessionId: string,
  message: string,
  handlers: {
    onThinking: (s: string) => void;
    onToken: (t: string) => void;
    onCard: (c: SSECard) => void;
    onSources: (items: { title: string; category: string }[]) => void;
    onDone: () => void;
    onError: (msg: string) => void;
  }
) {
  let resp: Response;
  try {
    resp = await fetch("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": "dev-local-key" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  } catch (e) {
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
        else if (evt.type === "token") handlers.onToken(evt.text);
        else if (evt.type === "card") handlers.onCard({ kind: evt.kind, data: evt.data });
        else if (evt.type === "sources") handlers.onSources(evt.items);
        else if (evt.type === "error") handlers.onError(evt.message ?? "服务异常");
        else if (evt.type === "done") handlers.onDone();
      }
    }
  } catch (e) {
    handlers.onError("连接中断，请稍后重试");
    handlers.onDone();
  }
}
