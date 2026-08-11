const SEED = ["会话 1", "会话 2", "会话 3"];
export default function SessionList({ active, onNew, onSelect }: {
  active: string; onNew: () => void; onSelect: (id: string) => void;
}) {
  return (
    <aside className="w-52 border-r bg-gray-50 flex flex-col">
      <div className="p-3 border-b">
        <button className="w-full bg-blue-500 text-white rounded py-1.5 text-sm hover:bg-blue-600" onClick={onNew}>+ 新建会话</button>
      </div>
      <ul className="flex-1 overflow-y-auto">
        {SEED.map((s) => (
          <li key={s} onClick={() => onSelect(s)}
              className={`px-3 py-2 cursor-pointer text-sm hover:bg-gray-100 ${active === s ? "bg-blue-100 font-medium" : ""}`}>{s}</li>
        ))}
      </ul>
    </aside>
  );
}
