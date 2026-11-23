export function TableWrap({ children }: { children: React.ReactNode }) {
  return <div className="overflow-x-auto rounded-xl border border-line/80 shadow-sm shadow-slate-200/60">{children}</div>;
}

export const tableClass = "w-full border-collapse text-left text-sm";
export const theadRowClass = "border-b border-line bg-slate-50/90 text-xs font-bold uppercase tracking-wide text-slate-500";
export const thClass = "px-5 py-3.5";
export const trClass = "border-b border-line/80 align-top transition-colors duration-150 last:border-0 hover:bg-emerald-50/45";
export const tdClass = "px-5 py-4 text-slate-700";
