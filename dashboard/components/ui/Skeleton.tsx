export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-skeleton rounded-lg bg-slate-200/80 ${className}`} />;
}

export function TableSkeleton({ rows = 5, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line/80 bg-white">
      <div className="grid gap-px bg-line/60">
        {Array.from({ length: rows }).map((_, row) => (
          <div key={row} className="grid gap-4 bg-white p-4" style={{ gridTemplateColumns: `repeat(${columns}, minmax(120px, 1fr))` }}>
            {Array.from({ length: columns }).map((__, column) => (
              <Skeleton key={column} className="h-5" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function FeedSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="grid gap-4">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="grid grid-cols-[40px_1fr] gap-3 rounded-xl border border-line/80 bg-white p-3">
          <Skeleton className="h-10 w-10 rounded-full" />
          <div className="grid gap-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="h-4 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}
