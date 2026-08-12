"use client";
import { useEffect, useState } from "react";
import SessionList from "../components/SessionList";
import ChatWindow from "../components/ChatWindow";
import ContextPanel from "../components/ContextPanel";

export default function Home() {
  // sessionId 依赖 Date.now()，不能在 useState 初始化里生成（SSR 与 CSR 值不一致会 Hydration 失败），
  // 改为仅客户端 useEffect 生成；初始为空串，挂载后立即填充，用户来得及输入前已就绪。
  const [sessionId, setSessionId] = useState("");
  const [sources, setSources] = useState<{ title: string; category: string }[]>([]);
  const [thinking, setThinking] = useState("");

  useEffect(() => { setSessionId(`sess-${Date.now()}`); }, []);

  return (
    <main className="h-screen flex">
      <SessionList active={sessionId} onNew={() => setSessionId(`sess-${Date.now()}`)} onSelect={() => {}} />
      <div className="flex-1 flex flex-col">
        <header className="h-12 border-b flex items-center px-4">
          <h1 className="font-bold">电商售后智能客服工作台</h1>
          <span className="ml-3 text-xs text-gray-400">{sessionId}</span>
        </header>
        <ChatWindow sessionId={sessionId} onSources={setSources} onThinking={setThinking} />
      </div>
      <ContextPanel sources={sources} thinking={thinking} />
    </main>
  );
}
