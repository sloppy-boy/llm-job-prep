"use client";
import { useState } from "react";
import SessionList from "../components/SessionList";
import ChatWindow from "../components/ChatWindow";
import ContextPanel from "../components/ContextPanel";

export default function Home() {
  const [sessionId, setSessionId] = useState(`sess-${Date.now()}`);
  const [sources, setSources] = useState<{ title: string; category: string }[]>([]);
  const [thinking, setThinking] = useState("");

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
