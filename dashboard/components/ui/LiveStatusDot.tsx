type Tone = "success" | "warning" | "error" | "info" | "muted";

const toneClass: Record<Tone, string> = {
  success: "bg-emerald-500 shadow-emerald-500/40",
  warning: "bg-amber-500 shadow-amber-500/40",
  error: "bg-red-500 shadow-red-500/40",
  info: "bg-sky-500 shadow-sky-500/40",
  muted: "bg-slate-400 shadow-slate-400/30",
};

export function LiveStatusDot({ tone = "success", label }: { tone?: Tone; label?: string }) {
  return (
    <span className="relative inline-flex h-2.5 w-2.5" aria-label={label}>
      <span className={`absolute inline-flex h-full w-full animate-soft-ping rounded-full opacity-40 ${toneClass[tone]}`} />
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full shadow-sm ${toneClass[tone]}`} />
    </span>
  );
}
