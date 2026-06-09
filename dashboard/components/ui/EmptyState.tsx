export function EmptyState({ title, message }: { title: string; message?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-slate-50 px-6 py-10 text-center transition-colors duration-150">
      <p className="text-sm font-bold text-ink">{title}</p>
      {message ? <p className="mt-1 text-sm text-muted">{message}</p> : null}
    </div>
  );
}
