"use client";
import { useEffect, useState } from "react";
import { fetchSessions, type SessionItem } from "@/lib/api";

export default function SessionList({ active, onNew, onSelect }: {
  active: string; onNew: () => void; onSelect: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<SessionItem[]>([]);

  // 挂载时拉一次真实会话列表（预览用后端 preview 字段）
  useEffect(() => {
    fetchSessions().then(setSessions);
  }, []);

  return (
    <aside className="w-52 border-r bg-gray-50 flex flex-col">
      <div className="p-3 border-b">
        <button className="w-full bg-blue-500 text-white rounded py-1.5 text-sm hover:bg-blue-600" onClick={onNew}>+ 新建会话</button>
      </div>
      <ul className="flex-1 overflow-y-auto">
        {sessions.length === 0 && (
          <li className="px-3 py-8 text-center text-xs text-gray-400">暂无会话</li>
        )}
        {sessions.map((s) => (
          <li key={s.session_id} onClick={() => onSelect(s.session_id)}
              className={`px-3 py-2 cursor-pointer hover:bg-gray-100 ${active === s.session_id ? "bg-blue-100 font-medium" : ""}`}>
            <div className="text-sm truncate">{s.preview || s.session_id}</div>
            <div className="text-xs text-gray-400 truncate">{s.session_id}</div>
          </li>
        ))}
      </ul>
    </aside>
  );
}
