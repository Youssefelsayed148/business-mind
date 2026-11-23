import type { ActivityLog } from "@/lib/types";

export type LogGroup = {
  id: string;
  title: string;
  logs: ActivityLog[];
  kind: "group" | "single";
};

const flowEvents = new Set([
  "webhook_received",
  "webhook_processed",
  "campaign_matched",
  "message_created",
  "message_queued",
  "message_sent",
  "message_failed",
]);

function metadataKey(log: ActivityLog) {
  const metadata = log.metadata || {};
  return String(metadata.comment_id || metadata.provider_message_id || log.campaign_id || "");
}

function canGroup(log: ActivityLog) {
  return flowEvents.has(log.event_type);
}

export function groupLogFlow(logs: ActivityLog[]): LogGroup[] {
  const groups: LogGroup[] = [];
  let index = 0;

  while (index < logs.length) {
    const current = logs[index];
    const key = metadataKey(current);
    if (!canGroup(current) || !key) {
      groups.push({ id: current.id, title: current.event_type, logs: [current], kind: "single" });
      index += 1;
      continue;
    }

    const children = [current];
    let nextIndex = index + 1;
    while (nextIndex < logs.length && canGroup(logs[nextIndex]) && metadataKey(logs[nextIndex]) === key) {
      children.push(logs[nextIndex]);
      nextIndex += 1;
    }

    if (children.length > 1) {
      groups.push({
        id: children.map((log) => log.id).join("-"),
        title: "Message flow",
        logs: children,
        kind: "group",
      });
    } else {
      groups.push({ id: current.id, title: current.event_type, logs: [current], kind: "single" });
    }
    index = nextIndex;
  }

  return groups;
}
