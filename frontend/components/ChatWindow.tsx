"use client";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import MessageCard from "./MessageCard";
import { streamChat, type ChatMessage } from "@/lib/sse";
import { fetchHistory, submitFeedback } from "@/lib/api";

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
  const [ratingError, setRatingError] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // 当前进行中流的取消句柄；null 表示当前没有可取消的流
  const cancelRef = useRef<(() => void) | null>(null);
  // 当前会话 id 的实时镜像，供流式回调判断自身是否已过期（会话切换竞态防护）
  const sessionRef = useRef(sessionId);

  // 评分点击：先提交后端，成功才落本地 rating（此后禁用）；失败可重试并短暂提示
  async function rate(n: number) {
    if (rating !== null) return;
    const ok = await submitFeedback(sessionId, n);
    if (ok) {
      setRating(n);
      setRatingError(false);
    } else {
      setRatingError(true);
      setTimeout(() => setRatingError(false), 3000);
    }
  }

  // 新消息/流式 token 到达时，滚动容器自动贴底，避免内容多了要手动下滑才能看到回复
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // 切换会话时重置聊天区并加载该会话历史；
  // 新建会话的 sessionId 是全新的 → fetchHistory 返回空 → messages 清空回到欢迎态。
  // cancelled 标志防止快速切换时旧会话的慢响应覆盖新会话历史。
  // 同时 abort 正在进行的旧流（取消句柄），并复位 busy，防止旧 token 污染新会话消息。
  useEffect(() => {
    if (!sessionId) return;
    sessionRef.current = sessionId;
    let cancelled = false;
    cancelRef.current?.();
    cancelRef.current = null;
    setBusy(false);
    setMessages([]);
    setRating(null);
    setRatingError(false);
    setInput("");
    fetchHistory(sessionId).then((h) => {
      if (cancelled) return;
      setMessages(h.map((m) => ({ role: m.role, content: m.content })));
    });
    return () => { cancelled = true; };
  }, [sessionId]);

  function send(text?: string) {
    const userText = (text ?? input).trim();
    if (!userText || busy) return;
    setInput(""); setBusy(true); setRating(null); setRatingError(false);
    setMessages((ms) => [...ms, { role: "user", content: userText }, { role: "assistant", content: "", cards: [] }]);
    onThinking("正在识别问题类别...");
    // streamChat 立刻返回 promise，并在微任务里 resolve { cancel }；不等流结束即可拿到取消句柄。
    // 回调里的 sessionRef 守卫：会话切换后旧流的迟到回调被丢弃，杜绝旧 token 污染新会话。
    const p = streamChat(sessionId, userText, {
      onThinking: (s) => {
        if (sessionRef.current !== sessionId) return;
        onThinking(s);
      },
      onToken: (t) => {
        if (sessionRef.current !== sessionId) return;
        setMessages((ms) => {
          const next = [...ms];
          const last = { ...next[next.length - 1], content: next[next.length - 1].content + t };
          next[next.length - 1] = last;
          return next;
        });
      },
      onCard: (c) => {
        if (sessionRef.current !== sessionId) return;
        setMessages((ms) => {
          const next = [...ms];
          const last = { ...next[next.length - 1], cards: [...(next[next.length - 1].cards ?? []), c] };
          next[next.length - 1] = last;
          return next;
        });
      },
      onSources: (items) => {
        if (sessionRef.current !== sessionId) return;
        onSources(items);
      },
      onError: (msg) => {
        if (sessionRef.current !== sessionId) return;
        setMessages((ms) => {
          const next = [...ms];
          const last = { ...next[next.length - 1], content: msg };
          next[next.length - 1] = last;
          return next;
        });
        onThinking(""); setBusy(false); cancelRef.current = null;
      },
      onDone: () => { onThinking(""); setBusy(false); cancelRef.current = null; },
    });
    p.then(({ cancel }) => { cancelRef.current = cancel; });
  }

  return (
    <div className="flex flex-col h-full">
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
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
              {m.role === "assistant" ? (
                <div className="[&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-gray-300 [&_table_th]:border [&_table_th]:border-gray-300 [&_table_th]:px-2 [&_table_th]:py-1 [&_table_td]:border [&_table_td]:border-gray-300 [&_table_td]:px-2 [&_table_td]:py-1 [&_pre]:bg-gray-800 [&_pre]:text-gray-100 [&_pre]:p-3 [&_pre]:rounded [&_pre]:overflow-x-auto [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_code]:bg-gray-200 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                  {busy && i === messages.length - 1 && (
                    <span className="inline-block animate-pulse">▍</span>
                  )}
                </div>
              ) : (
                m.content
              )}
              {m.cards?.map((c, j) => <MessageCard key={j} card={c} />)}
            </div>
          </div>
        ))}
      </div>
      <div className="p-3 border-t flex gap-2">
        <input className="flex-1 border rounded px-3 py-2" value={input} placeholder="输入问题…"
               onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && send()} />
        {busy && (
          <button className="bg-gray-500 text-white px-4 rounded hover:bg-gray-600"
                  onClick={() => { cancelRef.current?.(); cancelRef.current = null; setBusy(false); }}>
            ⏹ 停止
          </button>
        )}
        <button className="bg-blue-500 text-white px-4 rounded hover:bg-blue-600 disabled:opacity-50"
                onClick={() => send()} disabled={busy}>发送</button>
      </div>
      {messages.length > 0 && !busy && (
        <div className="px-4 pb-2 text-xs text-gray-400">
          {rating === null
            ? <>本次解答满意吗？{[1,2,3,4,5].map((n) => <button key={n} className="mx-0.5 hover:scale-110" onClick={() => rate(n)}>{n}⭐</button>)}</>
            : "感谢评价！"}
          {ratingError && <span className="ml-2 text-red-500">提交失败</span>}
        </div>
      )}
    </div>
  );
}
