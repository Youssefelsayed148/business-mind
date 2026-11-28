import type { ManyLog } from "./types";

export type LogGroup = {
  id: string;
  title: string;
  logs: ManyLog[];
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

function metadataKey(log: ManyLog): string {
  const metadata = log.metadata || {};
  return String(
    metadata.comment_id ||
      metadata.provider_message_id ||
      log.campaign_id ||
      "",
  );
}

function canGroup(log: ManyLog): boolean {
  return flowEvents.has(log.event_type);
}

/** Consecutive flow events that share a comment, provider message or campaign become one group. */
export function groupLogFlow(logs: ManyLog[]): LogGroup[] {
  const groups: LogGroup[] = [];
  let index = 0;
  while (index < logs.length) {
    const current = logs[index];
    const key = metadataKey(current);
    if (!canGroup(current) || !key) {
      groups.push({
        id: current.id,
        title: current.event_type,
        logs: [current],
        kind: "single",
      });
      index += 1;
      continue;
    }
    const children = [current];
    let next = index + 1;
    while (
      next < logs.length &&
      canGroup(logs[next]) &&
      metadataKey(logs[next]) === key
    ) {
      children.push(logs[next]);
      next += 1;
    }
    if (children.length > 1) {
      groups.push({
        id: children.map((log) => log.id).join("-"),
        title: "Message flow",
        logs: children,
        kind: "group",
      });
    } else {
      groups.push({
        id: current.id,
        title: current.event_type,
        logs: [current],
        kind: "single",
      });
    }
    index = next;
  }
  return groups;
}
