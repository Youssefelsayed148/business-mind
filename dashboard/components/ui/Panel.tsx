export function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-line/80 bg-white p-5 shadow-sm shadow-slate-200/60 transition duration-150 ease-out ${className}`}>
      {children}
    </section>
  );
}
