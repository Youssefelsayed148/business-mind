export function PageHeader({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 max-w-full flex-wrap items-end justify-between gap-4 overflow-hidden">
      <div className="min-w-0 max-w-2xl">
        <h1 className="text-3xl font-bold tracking-normal text-ink">{title}</h1>
        {description ? <p className="mt-2 text-sm leading-6 text-muted">{description}</p> : null}
      </div>
      {children ? <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">{children}</div> : null}
    </div>
  );
}
