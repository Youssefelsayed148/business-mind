"use client";

import { useCallback, useEffect, useState } from "react";

import { ManyError } from "@/lib/many";
import { Button, Empty, Loading, Notice } from "@/lib/ui";

import { staffGet } from "./calls";
import { mediaPath, mediaTypeLabel } from "./helpers";
import type { InstagramMedia, InstagramMediaResponse } from "./types";

/**
 * The account's recent posts (GET .../media, 24 per page). With `onSelect` a post can be
 * chosen (the campaign form); without it the grid is a read-only list (the accounts page).
 */
export function PostPicker({
  accountId,
  selectedMediaId = null,
  onSelect,
}: {
  accountId: string;
  selectedMediaId?: string | null;
  onSelect?: (media: InstagramMedia) => void;
}) {
  const [media, setMedia] = useState<InstagramMedia[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (cursor?: string) => {
      if (!accountId) return;
      if (cursor) setLoadingMore(true);
      else setLoading(true);
      setError(null);
      try {
        const data = await staffGet<InstagramMediaResponse>(
          mediaPath(accountId, cursor),
        );
        setMedia((current) =>
          cursor ? [...current, ...data.media] : data.media,
        );
        setNextCursor(data.next_cursor || null);
      } catch (caught) {
        setError(
          caught instanceof ManyError
            ? caught.message
            : "Could not load posts from Instagram. Check the account connection.",
        );
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [accountId],
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      setMedia([]);
      setNextCursor(null);
      void load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  if (!accountId) {
    return (
      <p className="muted">
        Select an Instagram account first to choose a post.
      </p>
    );
  }
  if (loading) return <Loading label="Loading posts from Instagram..." />;
  if (error) {
    return (
      <div data-testid="ig-media-error">
        <Notice
          tone="error"
          message={error}
          onRetry={() => void load()}
          retryLabel="Retry"
        />
      </div>
    );
  }
  if (media.length === 0) {
    return <Empty>No posts found on this Instagram account.</Empty>;
  }

  return (
    <div className="ig-media" data-testid="ig-media">
      <ul className="ig-media-grid">
        {media.map((item) => {
          const selected = selectedMediaId === item.media_id;
          const body = (
            <>
              <span className="ig-media-thumb">
                {item.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={item.thumbnail_url}
                    alt={item.label}
                    loading="lazy"
                    referrerPolicy="no-referrer"
                  />
                ) : (
                  <span className="muted">No preview</span>
                )}
                {selected && (
                  <span className="ig-media-selected">Selected</span>
                )}
              </span>
              <span className="ig-media-kind">
                {mediaTypeLabel(item.media_type)}
              </span>
              <span className="ig-media-label" dir="auto">
                {item.label}
              </span>
            </>
          );
          return (
            <li key={item.media_id}>
              {onSelect ? (
                <button
                  type="button"
                  className="ig-media-card"
                  data-testid={`ig-media-${item.media_id}`}
                  aria-pressed={selected}
                  onClick={() => onSelect(item)}
                >
                  {body}
                </button>
              ) : (
                <div className="ig-media-card">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
      {nextCursor && (
        <Button
          variant="quiet"
          disabled={loadingMore}
          onClick={() => void load(nextCursor)}
        >
          {loadingMore ? "Loading..." : "Load more posts"}
        </Button>
      )}
    </div>
  );
}
