// 服务间认证 Key：dev 默认 dev-local-key，生产通过 NEXT_PUBLIC_API_KEY 环境变量配置（构建期内联）
// 与 lib/sse.ts 保持一致，供会话列表/历史加载等普通 JSON 请求复用。
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "dev-local-key";

// 后端直连根地址（构建期内联），与 lib/sse.ts 一致：Next 的 rewrites 代理对流式及
// 长耗时请求不可靠（实测会中途掐断，导致回填这类几十秒的请求前端拿到"失败"），
// 留空回退相对路径走代理（默认行为），本地/演示设为后端地址即绕过代理直连。
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export type SessionItem = { session_id: string; updated_at?: string; preview?: string };
export type HistoryMessage = { role: "user" | "assistant"; content: string };

export async function fetchSessions(): Promise<SessionItem[]> {
  const r = await fetch(`${API_BASE}/api/v1/sessions`, { headers: { "X-API-Key": API_KEY } });
  if (!r.ok) return [];
  return (await r.json()).sessions ?? [];
}

export async function fetchHistory(sessionId: string): Promise<HistoryMessage[]> {
  const r = await fetch(`${API_BASE}/api/v1/sessions/${sessionId}/messages`, { headers: { "X-API-Key": API_KEY } });
  if (!r.ok) return [];
  return (await r.json()).messages ?? [];
}

// 评分反馈闭环：POST /api/v1/feedback，成功返回 true；网络/非 2xx 均视为失败（可重试）
export async function submitFeedback(sessionId: string, rating: number): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify({ session_id: sessionId, rating }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

// ---- 知识库回填闭环：人工回复 → 沉淀草稿 → 审批发布 ----

export type BackfillResult = { status: string; doc_id: string; path: string; title: string };

// 提交人工客服回复：POST /api/v1/sessions/{id}/human-reply，成功返回 true
export async function humanReply(sessionId: string, question: string, answer: string): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/sessions/${sessionId}/human-reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify({ question, answer }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

// 沉淀草稿：POST /api/v1/kb/backfill，成功返回草稿信息，失败返回 null
export async function backfill(question: string, answer: string): Promise<BackfillResult | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/kb/backfill`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify({ question, answer }),
    });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

// 审批发布草稿：POST /api/v1/kb/backfill/{docId}/approve，成功返回 true
export async function approveBackfill(docId: string): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/kb/backfill/${encodeURIComponent(docId)}/approve`, {
      method: "POST",
      headers: { "X-API-Key": API_KEY },
    });
    return r.ok;
  } catch {
    return false;
  }
}
