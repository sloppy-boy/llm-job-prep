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
  }
) {
  const resp = await fetch("http://localhost:8000/api/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": "dev-local-key" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const evt = JSON.parse(line.slice(6));
      if (evt.type === "thinking") handlers.onThinking(evt.status);
      else if (evt.type === "token") handlers.onToken(evt.text);
      else if (evt.type === "card") handlers.onCard({ kind: evt.kind, data: evt.data });
      else if (evt.type === "sources") handlers.onSources(evt.items);
      else if (evt.type === "done") handlers.onDone();
    }
  }
}
