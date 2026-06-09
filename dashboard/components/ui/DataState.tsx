export function DataState({ error, loading }: { error?: string | null; loading?: boolean }) {
  if (loading) return <p className="rounded-lg border border-line bg-panel px-4 py-3 text-sm font-medium text-muted">Loading...</p>;
  if (error) return <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-danger">{error}</p>;
  return null;
}
