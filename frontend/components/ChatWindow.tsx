"use client";
import { useState } from "react";
import MessageCard from "./MessageCard";
import { streamChat, type ChatMessage } from "@/lib/sse";

const SUGGESTIONS = ["怎么申请退货？", "订单到哪了？", "退款多久到账？"];

export default function ChatWindow({ sessionId, onSources, onThinking }: {
  sessionId: string;
  onSources: (items: { title: string; category: string }[]) => void;
  onThinking: (s: string) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [rating, setRating] = useState<number | null>(null);

  async function send(text?: string) {
    const userText = (text ?? input).trim();
    if (!userText || busy) return;
    setInput(""); setBusy(true); setRating(null);
    setMessages((ms) => [...ms, { role: "user", content: userText }, { role: "assistant", content: "", cards: [] }]);
    onThinking("正在识别问题类别...");
    await streamChat(sessionId, userText, {
      onThinking: (s) => onThinking(s),
      onToken: (t) => setMessages((ms) => {
        const next = [...ms];
        const last = { ...next[next.length - 1], content: next[next.length - 1].content + t };
        next[next.length - 1] = last;
        return next;
      }),
      onCard: (c) => setMessages((ms) => {
        const next = [...ms];
        const last = { ...next[next.length - 1], cards: [...(next[next.length - 1].cards ?? []), c] };
        next[next.length - 1] = last;
        return next;
      }),
      onSources: (items) => onSources(items),
      onDone: () => { onThinking(""); setBusy(false); },
    });
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 mt-20">
            <p className="text-3xl mb-2">💬</p>
            <p>你好，我是智能客服小商，有什么可以帮您？</p>
            <div className="flex gap-2 justify-center mt-4">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="border rounded-full px-3 py-1 text-sm hover:bg-gray-100" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <div className={`inline-block rounded-lg px-3 py-2 text-left max-w-md ${m.role === "user" ? "bg-blue-500 text-white" : "bg-gray-100"}`}>
              {m.content}
              {m.cards?.map((c, j) => <MessageCard key={j} card={c} />)}
            </div>
          </div>
        ))}
      </div>
      <div className="p-3 border-t flex gap-2">
        <input className="flex-1 border rounded px-3 py-2" value={input} placeholder="输入问题…"
               onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && send()} />
        <button className="bg-blue-500 text-white px-4 rounded hover:bg-blue-600" onClick={() => send()}>发送</button>
      </div>
      {messages.length > 0 && !busy && (
        <div className="px-4 pb-2 text-xs text-gray-400">
          {rating === null
            ? <>本次解答满意吗？{[1,2,3,4,5].map((n) => <button key={n} className="mx-0.5 hover:scale-110" onClick={() => setRating(n)}>{n}⭐</button>)}</>
            : "感谢评价！"}
        </div>
      )}
    </div>
  );
}
