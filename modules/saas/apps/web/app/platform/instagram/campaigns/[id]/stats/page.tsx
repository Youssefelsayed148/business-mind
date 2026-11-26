"use client";

import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";

import { ManyError } from "@/lib/many";
import { staffGet, staffSend } from "@/lib/many-instagram/calls";
import {
  failedMessageIds,
  formatDateTime,
  targetLabel,
} from "@/lib/many-instagram/helpers";
import type { CampaignStats } from "@/lib/many-instagram/types";
import { PageState } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import {
  Button,
  Card,
  Empty,
  LinkButton,
  Notice,
  PageHeader,
  StatCard,
  StatusBadge,
} from "@/lib/ui";

import "@/app/instagram-screen.css";

const LIST = "/platform/instagram/campaigns";

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ig-detail">
      <dt>{label}</dt>
      <dd>{children || "Unknown"}</dd>
    </div>
  );
}

function words(value: string) {
  return value.replace(/_/g, " ");
}

function ExternalLink({ href }: { href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      dir="ltr"
      className="ig-url"
    >
      {href}
    </a>
  );
}

/** Stats and recent activity for one Instagram campaign (platform staff). */
export default function InstagramCampaignStatsPage() {
  const { id } = useParams<{ id: string }>();
  const {
    data: stats,
    status,
    reload,
  } = useManyData(
    () => staffGet<CampaignStats>(`/campaigns/${encodeURIComponent(id)}/stats`),
    id,
  );
  const [retrying, setRetrying] = useState(false);
  const [result, setResult] = useState<{
    text: string;
    tone: "info" | "error";
  } | null>(null);

  const failed = failedMessageIds(stats?.recent_messages ?? []);

  async function retryFailed() {
    setRetrying(true);
    setResult(null);
    try {
      await Promise.all(
        failed.map((messageId) =>
          staffSend("POST", `/messages/${encodeURIComponent(messageId)}/retry`),
        ),
      );
      setResult({ text: "Failed messages queued for retry.", tone: "info" });
      reload();
    } catch (caught) {
      setResult({
        text:
          caught instanceof ManyError
            ? caught.message
            : "Could not retry the messages.",
        tone: "error",
      });
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="ig-page" data-testid="ig-stats">
      <PageHeader
        title={
          stats ? <span dir="auto">{stats.name}</span> : "Campaign details"
        }
        actions={
          <>
            <LinkButton href={`${LIST}/${id}`}>Edit</LinkButton>
            <Button
              variant="quiet"
              disabled={retrying || failed.length === 0}
              data-testid="ig-retry-failed"
              onClick={() => void retryFailed()}
            >
              {retrying ? "Retrying..." : "Retry failed"}
            </Button>
          </>
        }
      />
      {result && (
        <Notice tone={result.tone} message={result.text} scope="item" />
      )}
      <PageState status={status} homeHref={LIST}>
        {stats && (
          <>
            <Card title="Overview">
              <p className="ig-badges">
                <StatusBadge value={stats.status} />
                <StatusBadge value={stats.delivery_mode} tone="info" />
                <span className="muted">
                  Created {formatDateTime(stats.created_at)}
                </span>
              </p>
              <dl className="ig-details-grid">
                <Detail label="Created by">{stats.created_by}</Detail>
                <Detail label="Instagram account">
                  <span dir="auto">
                    {stats.account_username || stats.account_ig_user_id}
                  </span>
                </Detail>
                <Detail label="Target">
                  <span dir="auto">{targetLabel(stats)}</span>
                  {stats.target_media_url && (
                    <>
                      <br />
                      <ExternalLink href={stats.target_media_url} />
                    </>
                  )}
                </Detail>
                <Detail label="Match type">{words(stats.match_type)}</Detail>
                <Detail label="Cooldown period">{`${stats.cooldown_hours} hours`}</Detail>
                <Detail label="Keywords">
                  {stats.keywords.length ? (
                    <span className="ig-chips">
                      {stats.keywords.map((keyword) => (
                        <span key={keyword} className="ig-chip" dir="auto">
                          {keyword}
                        </span>
                      ))}
                    </span>
                  ) : (
                    "No keywords"
                  )}
                </Detail>
              </dl>
            </Card>

            <Card title="Message">
              <dl className="ig-details-grid">
                <Detail label="Final DM message or template">
                  <pre className="ig-pre" dir="auto">
                    {stats.message_template}
                  </pre>
                </Detail>
                <Detail label="Link URL">
                  {stats.link_url ? (
                    <ExternalLink href={stats.link_url} />
                  ) : (
                    "Not configured"
                  )}
                </Detail>
              </dl>
              <p className="muted">
                Supported variables include username, campaign name, keyword,
                link and media URL.
              </p>
            </Card>

            {stats.delivery_mode === "follow_prompt" && (
              <Card title="Follow prompt">
                <dl className="ig-details-grid">
                  <Detail label="Card title">
                    <span dir="auto">{stats.follow_prompt_title}</span>
                  </Detail>
                  <Detail label="Profile URL">
                    {stats.follow_prompt_profile_url && (
                      <ExternalLink href={stats.follow_prompt_profile_url} />
                    )}
                  </Detail>
                  <Detail label="Card description">
                    <span dir="auto">{stats.follow_prompt_description}</span>
                  </Detail>
                  <Detail label="Button and delay">
                    Follow, then final message after 10 seconds
                  </Detail>
                </dl>
                <p className="muted">
                  The system does not verify whether the user followed.
                </p>
              </Card>
            )}

            <div className="ig-kpis" data-testid="ig-kpis">
              <StatCard label="Total triggers" value={stats.total_triggers} />
              <StatCard
                label="Successful sends"
                value={stats.successful_sends}
              />
              <StatCard label="Failed sends" value={stats.failed_sends} />
              <StatCard label="New leads" value={stats.new_leads} />
              <StatCard
                label="Last triggered"
                value={formatDateTime(stats.last_triggered_at)}
              />
              <StatCard label="Cooldowns" value={stats.cooldowns} />
            </div>

            <Card title="Recent messages">
              {stats.recent_messages.length === 0 ? (
                <Empty>No recent messages.</Empty>
              ) : (
                <ul className="ig-feed" data-testid="ig-messages">
                  {stats.recent_messages.map((message) => (
                    <li key={message.id}>
                      <p className="ig-badges">
                        <StatusBadge value={message.status} />
                        <strong dir="auto">
                          {message.username || "Unknown user"}
                        </strong>
                        <span className="muted">
                          {formatDateTime(
                            message.sent_at || message.created_at,
                          )}
                        </span>
                      </p>
                      {message.error_message ? (
                        <p className="ig-error" dir="auto">
                          {message.error_message}
                        </p>
                      ) : (
                        <p className="muted">
                          {words(message.message_type || "final_delivery")}
                        </p>
                      )}
                      <details>
                        <summary>Technical details</summary>
                        <pre className="ig-pre" dir="ltr">
                          {JSON.stringify(message, null, 2)}
                        </pre>
                      </details>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Recent logs">
              {stats.recent_logs.length === 0 ? (
                <Empty>No recent logs.</Empty>
              ) : (
                <ul className="ig-feed" data-testid="ig-logs">
                  {stats.recent_logs.map((log) => (
                    <li key={log.id}>
                      <p className="ig-badges">
                        <strong>{words(log.event_type)}</strong>
                        <span className="muted">
                          {formatDateTime(log.created_at)}
                        </span>
                      </p>
                      <p className="muted" dir="auto">
                        {log.message}
                      </p>
                      <details>
                        <summary>Technical details</summary>
                        <pre className="ig-pre" dir="ltr">
                          {JSON.stringify(log.metadata, null, 2)}
                        </pre>
                      </details>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </>
        )}
      </PageState>
      <p>
        <LinkButton href={LIST} variant="ghost">
          Back to campaigns
        </LinkButton>
      </p>
    </div>
  );
}
