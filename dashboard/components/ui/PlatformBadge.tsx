const labelMap: Record<string, string> = {
  instagram: "Instagram",
  whatsapp: "WhatsApp",
  facebook: "Facebook",
};

function platformLabel(value?: string | null) {
  if (!value) return "Unknown";
  return labelMap[value] || value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function PlatformBadge({ platform }: { platform?: string | null }) {
  return (
    <span className="inline-flex rounded-full border border-line bg-white px-2.5 py-1 text-xs font-semibold text-ink shadow-sm">
      {platformLabel(platform)}
    </span>
  );
}
