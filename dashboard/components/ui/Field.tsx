import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

type BaseProps = {
  label: string;
  hint?: string;
};

export function Field({ label, hint, ...props }: BaseProps & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="grid gap-1.5 text-sm font-semibold text-ink">
      <span>{label}</span>
      <input className="h-10 rounded-lg border border-line bg-white px-3 font-normal text-ink shadow-sm outline-none transition duration-150 placeholder:text-slate-400 hover:border-slate-300 focus:border-accent focus:ring-4 focus:ring-accent/15" {...props} />
      {hint ? <span className="text-xs font-normal text-muted">{hint}</span> : null}
    </label>
  );
}

export function TextArea({ label, hint, ...props }: BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <label className="grid gap-1.5 text-sm font-semibold text-ink">
      <span>{label}</span>
      <textarea className="min-h-28 rounded-lg border border-line bg-white px-3 py-2 font-normal text-ink shadow-sm outline-none transition duration-150 placeholder:text-slate-400 hover:border-slate-300 focus:border-accent focus:ring-4 focus:ring-accent/15" {...props} />
      {hint ? <span className="text-xs font-normal text-muted">{hint}</span> : null}
    </label>
  );
}

export function Select({ label, hint, children, ...props }: BaseProps & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <label className="grid gap-1.5 text-sm font-semibold text-ink">
      <span>{label}</span>
      <select className="h-10 rounded-lg border border-line bg-white px-3 font-normal text-ink shadow-sm outline-none transition duration-150 hover:border-slate-300 focus:border-accent focus:ring-4 focus:ring-accent/15" {...props}>
        {children}
      </select>
      {hint ? <span className="text-xs font-normal text-muted">{hint}</span> : null}
    </label>
  );
}
