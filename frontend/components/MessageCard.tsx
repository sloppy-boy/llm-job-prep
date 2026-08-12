// 渲染工具结果卡片。任何 kind 都先校验 data 形状再访问字段：
// 后端 error 结果（如订单不存在）不会推卡片，但这里仍需兜底，保证任意数据都不让页面崩溃。
const isObj = (d: any): d is Record<string, any> => !!d && typeof d === "object" && !Array.isArray(d);

export default function MessageCard({ card }: { card: { kind: string; data: any } }) {
  if (card.kind === "order" && isObj(card.data)) {
    const d = card.data;
    return (
      <div className="border rounded-lg p-3 my-2 bg-white shadow-sm">
        <div className="text-xs text-gray-500 mb-1">📦 订单 {d.order_id ?? "—"}</div>
        <div>状态：<b>{d.status ?? "—"}</b></div>
        <div className="text-xs text-gray-500 mt-1">{d.items ?? ""} {d.amount != null ? `· ¥${d.amount}` : ""}</div>
      </div>
    );
  }
  if (card.kind === "logistics" && Array.isArray(card.data)) {
    return (
      <div className="border rounded-lg p-3 my-2 bg-white shadow-sm">
        <div className="text-xs text-gray-500 mb-1">🚚 物流轨迹</div>
        {card.data.length === 0
          ? <div className="text-sm text-gray-500">暂无物流轨迹</div>
          : card.data.map((l: any, i: number) => (
              <div key={i} className="text-sm flex gap-2"><span className="text-gray-400">{l?.time}</span><span>{l?.event}</span></div>
            ))}
      </div>
    );
  }
  if (card.kind === "refund" && isObj(card.data)) {
    const d = card.data;
    return (
      <div className="border rounded-lg p-3 my-2 bg-white shadow-sm">
        <div className="text-xs text-gray-500 mb-1">💸 退款申请</div>
        <div>申请单：{d.refund_id ?? "—"} · 状态：{d.status ?? "—"}</div>
      </div>
    );
  }
  return null;
}
