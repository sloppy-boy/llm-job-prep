"use client";
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import MessageCard from "./MessageCard";
import { streamChat, type ChatMessage, MAX_HISTORY } from "@/lib/sse";
import { fetchHistory, submitFeedback, humanReply, backfill, approveBackfill } from "@/lib/api";

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
  // 评分提交进行中标记：await 期间屏蔽重复点击，防止双击并发 POST
  const submittingRef = useRef(false);
  // 最近一次提问文本，供转人工弹窗在 human_handoff 回调里补全「用户问题」
  const lastQuestionRef = useRef("");
  // 转人工弹窗状态：open 是否打开；question/answer 用户问题与人工回答；
  // step 阶段流转 reply(回复) → drafted(已沉淀草稿) → approved(已发布)；
  // draft 为 backfill 返回的草稿元信息；error 为各步失败提示
  const [handoff, setHandoff] = useState<{
    open: boolean; question: string; answer: string;
    step: "reply" | "drafted" | "approved";
    draft?: { doc_id: string; path: string; title: string };
    error?: string;
  }>({ open: false, question: "", answer: "", step: "reply" });

  // 评分点击：先提交后端，成功才落本地 rating（此后禁用）；失败可重试并短暂提示
  async function rate(n: number) {
    if (rating !== null || submittingRef.current) return;
    submittingRef.current = true;
    const ok = await submitFeedback(sessionId, n);
    submittingRef.current = false;
    if (ok) {
      setRating(n);
      setRatingError(false);
    } else {
      setRatingError(true);
      setTimeout(() => setRatingError(false), 3000);
    }
  }

  // 转人工流程第一步：提交人工客服回复。成功后追加一条「（人工客服）」消息并进入沉淀阶段。
  async function doHumanReply() {
    const a = handoff.answer.trim();
    if (!a || busy) return;
    setBusy(true);
    const ok = await humanReply(sessionId, handoff.question, a);
    setBusy(false);
    if (!ok) { setHandoff((h) => ({ ...h, error: "提交失败" })); return; }
    setMessages((ms) => [...ms, { role: "assistant", content: `（人工客服）${a}`, human: true }]);
    setHandoff((h) => ({ ...h, answer: a, step: "drafted", error: undefined }));
  }

  // 转人工流程第二步：沉淀为知识库草稿。exists 表示知识库已有类似条目，给出提示。
  async function doBackfill() {
    setBusy(true);
    const d = await backfill(handoff.question, handoff.answer);
    setBusy(false);
    if (!d || d.status === "exists") {
      setHandoff((h) => ({ ...h, error: d?.status === "exists" ? "知识库已存在类似条目" : "沉淀失败" }));
      return;
    }
    setHandoff((h) => ({ ...h, draft: d, error: undefined }));
  }

  // 转人工流程第三步：审批发布草稿，成功后短暂显示已发布再自动关闭弹窗。
  async function doApprove() {
    if (!handoff.draft) return;
    setBusy(true);
    const ok = await approveBackfill(handoff.draft.doc_id);
    setBusy(false);
    if (!ok) { setHandoff((h) => ({ ...h, error: "发布失败" })); return; }
    setHandoff((h) => ({ ...h, step: "approved", error: undefined }));
    setTimeout(() => setHandoff((h) => ({ ...h, open: false })), 2000);
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
    lastQuestionRef.current = userText;
    // 多轮上下文：把当前这轮之前的最近 N 条消息作为 history 带给后端
    // （模型据此理解"上一轮我说了什么"，不再是单轮失忆）
    const history = messages
      .slice(-MAX_HISTORY)
      .map((m) => ({ role: m.role, content: m.content }));
    setInput(""); setBusy(true); setRating(null); setRatingError(false);
    setMessages((ms) => [...ms, { role: "user", content: userText }, { role: "assistant", content: "", cards: [], retryText: userText, failed: false }]);
    onThinking("正在识别问题类型...");
    // streamChat 立刻返回 promise，并在微任务里 resolve { cancel }；不等流结束即可拿到取消句柄。
    // 回调里的 sessionRef 守卫：会话切换后旧流的迟到回调被丢弃，杜绝旧 token 污染新会话。
    const p = streamChat(sessionId, userText, history, {
      onThinking: (s) => {
        if (sessionRef.current !== sessionId) return;
        onThinking(s);
      },
      onToken: (t) => {
        if (sessionRef.current !== sessionId) return;
        // flushSync 强制每 token 同步提交渲染：React 18 自动批处理会把同事件循环内连续
        // setMessages 合并成一次渲染，导致"一次性蹦出"而非逐字打字效果
        flushSync(() => {
          setMessages((ms) => {
            const next = [...ms];
            const last = { ...next[next.length - 1], content: next[next.length - 1].content + t };
            next[next.length - 1] = last;
            return next;
          });
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
      onHandoff: () => {
        if (sessionRef.current !== sessionId) return;
        setMessages((ms) => {
          const next = [...ms];
          const i = next.length - 1;
          if (i >= 0 && next[i].role === "assistant") next[i] = { ...next[i], handoff: true };
          return next;
        });
        // 整体复位弹窗状态（回答清空、step 回 reply、清 error、清 draft），
        // 保证同会话第二次收到 human_handoff 时从回复步骤干净起步，而非停留在 approved/drafted。
        setHandoff({ open: false, question: lastQuestionRef.current, answer: "", step: "reply", error: undefined });
      },
      onError: (msg) => {
        if (sessionRef.current !== sessionId) return;
        setMessages((ms) => {
          const next = [...ms];
          const last = { ...next[next.length - 1], content: msg, failed: true };
          next[next.length - 1] = last;
          return next;
        });
        onThinking(""); setBusy(false); cancelRef.current = null;
      },
      onDone: () => {
        if (sessionRef.current !== sessionId) return;
        onThinking(""); setBusy(false); cancelRef.current = null;
      },
    });
    p.then(({ cancel }) => { cancelRef.current = cancel; });
  }

  // 回答失败重试：整轮移除失败的 user + assistant（避免重发时旧 user 消息重复显示），再用同一用户文本重新流式。
  // 调用时 busy 已为 false（onError 里已 setBusy(false)），send 内部会重新置 busy=true。
  function retry(m: ChatMessage) {
    if (!m.retryText || busy) return;
    setMessages((ms) => {
      const i = ms.indexOf(m);
      if (i < 0) return ms;
      const next = [...ms];
      // 失败的 assistant 上一条即对应的 user 消息，一并移除，整轮重发
      const start = i > 0 && next[i - 1].role === "user" ? i - 1 : i;
      next.splice(start, i - start + 1);
      return next;
    });
    send(m.retryText);
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
            {m.role === "assistant" && m.failed && (
              <button onClick={() => retry(m)} className="block ml-2 mt-1 text-xs border rounded px-2 py-1 text-gray-600 hover:bg-gray-100">
                🔄 重试
              </button>
            )}
            {m.role === "assistant" && m.handoff && !handoff.open && (
              <button onClick={() => setHandoff((h) => ({ ...h, open: true }))}
                      className="block ml-2 mt-1 text-xs border rounded px-2 py-1 text-amber-700 hover:bg-amber-50">
                🤝 转人工
              </button>
            )}
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
      {handoff.open && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
             onClick={() => setHandoff((h) => ({ ...h, open: false }))}>
          <div className="bg-white rounded-lg shadow-lg p-4 w-96 max-w-[90vw]"
               onClick={(e) => e.stopPropagation()}>
            {handoff.step === "reply" && (
              <>
                <h3 className="font-bold mb-2">🤝 人工客服（模拟）</h3>
                <p className="text-sm text-gray-600 mb-2">用户问题：{handoff.question}</p>
                <textarea className="border rounded w-full p-2 text-sm" rows={4}
                          placeholder="输入人工客服的回答…" value={handoff.answer}
                          onChange={(e) => setHandoff((h) => ({ ...h, answer: e.target.value }))} />
                {handoff.error && <p className="text-red-500 text-xs">{handoff.error}</p>}
                <div className="flex gap-2 mt-2 justify-end">
                  <button className="border rounded px-3 py-1 text-sm"
                          onClick={() => setHandoff((h) => ({ ...h, open: false }))}>取消</button>
                  <button className="bg-blue-500 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                          disabled={busy || !handoff.answer.trim()} onClick={doHumanReply}>回复</button>
                </div>
              </>
            )}
            {handoff.step === "drafted" && (
              <>
                <h3 className="font-bold mb-2">📥 沉淀到知识库</h3>
                {handoff.error && <p className="text-red-500 text-xs">{handoff.error}</p>}
                {!handoff.draft ? (
                  <button className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                          onClick={doBackfill}>沉淀</button>
                ) : (
                  <>
                    <p className="text-sm text-gray-600 mb-2">已生成草稿：{handoff.draft.title}</p>
                    <p className="text-xs text-gray-400 mb-2">路径：{handoff.draft.path}</p>
                    <div className="flex gap-2 justify-end">
                      <button className="border rounded px-3 py-1 text-sm"
                              onClick={() => setHandoff((h) => ({ ...h, open: false }))}>关闭</button>
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                              onClick={doApprove}>确认发布</button>
                    </div>
                  </>
                )}
              </>
            )}
            {handoff.step === "approved" && (
              <p className="text-green-600 font-bold">✅ 已发布，下次命中知识库</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
