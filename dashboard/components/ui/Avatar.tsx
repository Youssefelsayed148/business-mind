function initialsFor(value?: string | null) {
  if (!value) return "?";
  const words = value.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}

const tones = [
  "from-emerald-100 to-teal-50 text-emerald-800 border-emerald-200",
  "from-blue-100 to-sky-50 text-blue-800 border-blue-200",
  "from-violet-100 to-fuchsia-50 text-violet-800 border-violet-200",
  "from-amber-100 to-orange-50 text-amber-800 border-amber-200",
  "from-slate-100 to-slate-50 text-slate-700 border-slate-200",
];

function toneFor(value?: string | null) {
  const source = value || "";
  const index = Array.from(source).reduce((sum, char) => sum + char.charCodeAt(0), 0) % tones.length;
  return tones[index];
}

export function Avatar({ label, size = "md" }: { label?: string | null; size?: "sm" | "md" | "lg" }) {
  const sizes = {
    sm: "h-7 w-7 text-[10px]",
    md: "h-9 w-9 text-xs",
    lg: "h-10 w-10 text-sm",
  };
  return (
    <span className={`inline-flex shrink-0 items-center justify-center rounded-full border bg-gradient-to-br font-bold shadow-sm ${sizes[size]} ${toneFor(label)}`}>
      {initialsFor(label)}
    </span>
  );
}
