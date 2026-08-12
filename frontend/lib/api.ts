// 服务间认证 Key：dev 默认 dev-local-key，生产通过 NEXT_PUBLIC_API_KEY 环境变量配置（构建期内联）
// 与 lib/sse.ts 保持一致，供会话列表/历史加载等普通 JSON 请求复用。
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "dev-local-key";

export type SessionItem = { session_id: string; updated_at?: string; preview?: string };
export type HistoryMessage = { role: "user" | "assistant"; content: string };

export async function fetchSessions(): Promise<SessionItem[]> {
  const r = await fetch("/api/v1/sessions", { headers: { "X-API-Key": API_KEY } });
  if (!r.ok) return [];
  return (await r.json()).sessions ?? [];
}

export async function fetchHistory(sessionId: string): Promise<HistoryMessage[]> {
  const r = await fetch(`/api/v1/sessions/${sessionId}/messages`, { headers: { "X-API-Key": API_KEY } });
  if (!r.ok) return [];
  return (await r.json()).messages ?? [];
}
