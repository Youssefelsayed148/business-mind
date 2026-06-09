export function Highlight({ text, term }: { text?: string | null; term?: string | null }) {
  const value = text || "";
  const query = term?.trim();
  if (!query) return <>{value}</>;
  const lower = value.toLocaleLowerCase();
  const needle = query.toLocaleLowerCase();
  const index = lower.indexOf(needle);
  if (index === -1) return <>{value}</>;
  return (
    <>
      {value.slice(0, index)}
      <mark className="rounded bg-amber-100 px-0.5 text-inherit">{value.slice(index, index + query.length)}</mark>
      {value.slice(index + query.length)}
    </>
  );
}
