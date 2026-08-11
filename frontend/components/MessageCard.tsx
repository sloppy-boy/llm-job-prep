export default function MessageCard({ card }: { card: { kind: string; data: any } }) {
  if (card.kind === "order")
    return (
      <div className="border rounded-lg p-3 my-2 bg-white shadow-sm">
        <div className="text-xs text-gray-500 mb-1">📦 订单 {card.data.order_id}</div>
        <div>状态：<b>{card.data.status}</b></div>
        <div className="text-xs text-gray-500 mt-1">{card.data.items} · ¥{card.data.amount}</div>
      </div>
    );
  if (card.kind === "logistics")
    return (
      <div className="border rounded-lg p-3 my-2 bg-white shadow-sm">
        <div className="text-xs text-gray-500 mb-1">🚚 物流轨迹</div>
        {(card.data || []).map((l: any, i: number) => (
          <div key={i} className="text-sm flex gap-2"><span className="text-gray-400">{l.time}</span><span>{l.event}</span></div>
        ))}
      </div>
    );
  if (card.kind === "refund")
    return (
      <div className="border rounded-lg p-3 my-2 bg-white shadow-sm">
        <div className="text-xs text-gray-500 mb-1">💸 退款申请</div>
        <div>申请单：{card.data.refund_id} · 状态：{card.data.status}</div>
      </div>
    );
  return null;
}
