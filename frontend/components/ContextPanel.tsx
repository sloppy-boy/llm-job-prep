export default function ContextPanel({ sources, thinking }: {
  sources: { title: string; category: string }[];
  thinking: string;
}) {
  return (
    <aside className="w-60 border-l bg-gray-50 p-4 overflow-y-auto">
      <h3 className="text-sm font-bold mb-3">📚 RAG 知识命中</h3>
      {sources.length === 0
        ? <p className="text-xs text-gray-400">检索命中文档将显示在这里</p>
        : <ul className="space-y-2">{sources.map((s, i) => (
            <li key={i} className="text-xs bg-white border rounded p-2">
              <div className="font-medium">{s.title}</div>
              <div className="text-gray-400">{s.category}</div>
            </li>
          ))}</ul>}
      {thinking && <p className="text-xs text-gray-400 mt-4">⏳ {thinking}</p>}
    </aside>
  );
}
