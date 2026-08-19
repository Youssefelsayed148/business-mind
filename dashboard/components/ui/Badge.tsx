const labelMap: Record<string, string> = {
  active: "Active",
  draft: "Draft",
  paused: "Paused",
  archived: "Archived",
  connected: "Connected",
  disconnected: "Disconnected",
  inactive: "Inactive",
  token_expired: "Token Expired",
  expiring_soon: "Expiring Soon",
  reconnect_required: "Reconnect Required",
  sent: "Sent",
  failed: "Failed",
  expired: "Expired",
  skipped: "Cooldown",
  queued: "Queued",
  pending: "Pending",
  new: "New",
  instant: "Instant",
  follow_prompt: "Follow Prompt",
  contains: "Contains",
  exact: "Exact",
  starts_with: "Starts With",
  final_delivery: "Final Delivery",
  follow_prompt_message: "Follow Prompt",
  bot_active: "Bot Active",
  handed_off: "Handed Off",
  closed: "Closed",
  ai_conversation: "AI Reply",
  received: "Received",
};

const toneMap: Record<string, string> = {
  active: "border-emerald-200 bg-mint text-emerald-700",
  connected: "border-emerald-200 bg-mint text-emerald-700",
  sent: "border-emerald-200 bg-mint text-emerald-700",
  new: "border-blue-200 bg-blue-50 text-blue-700",
  queued: "border-blue-200 bg-blue-50 text-blue-700",
  pending: "border-blue-200 bg-blue-50 text-blue-700",
  failed: "border-red-200 bg-red-50 text-danger",
  reconnect_required: "border-red-200 bg-red-50 text-danger",
  expired: "border-red-200 bg-red-50 text-danger",
  token_expired: "border-red-200 bg-red-50 text-danger",
  expiring_soon: "border-amber-200 bg-amber-50 text-amber-700",
  disconnected: "border-amber-200 bg-amber-50 text-amber-700",
  inactive: "border-amber-200 bg-amber-50 text-amber-700",
  paused: "border-slate-300 bg-slate-100 text-slate-700",
  skipped: "border-amber-200 bg-amber-50 text-amber-700",
  draft: "border-slate-200 bg-slate-50 text-slate-600",
  archived: "border-slate-200 bg-slate-50 text-slate-600",
  bot_active: "border-emerald-200 bg-mint text-emerald-700",
  handed_off: "border-amber-200 bg-amber-50 text-amber-700",
  closed: "border-slate-200 bg-slate-50 text-slate-600",
  info: "border-blue-200 bg-blue-50 text-blue-700",
  warning: "border-amber-200 bg-amber-50 text-amber-700",
  error: "border-red-200 bg-red-50 text-danger",
};

export function statusLabel(value?: string | null) {
  if (!value) return "Unknown";
  return labelMap[value] || value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function Badge({ value }: { value?: string | null }) {
  const tone = value ? toneMap[value] : undefined;
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold shadow-sm transition-colors duration-150 ${tone || "border-line bg-white text-ink"}`}>
      {statusLabel(value)}
    </span>
  );
}
