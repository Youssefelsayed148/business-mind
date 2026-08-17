"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import type { InstagramMedia, InstagramMediaResponse } from "@/lib/types";

type PostPickerProps = {
  accountId: string;
  selectedMediaId: string | null;
  onSelect: (media: InstagramMedia) => void;
};

function mediaTypeLabel(mediaType: string): string {
  switch (mediaType) {
    case "VIDEO":
      return "Reel/Video";
    case "CAROUSEL_ALBUM":
      return "Carousel";
    case "IMAGE":
      return "Post";
    default:
      return "Post";
  }
}

export function PostPicker({ accountId, selectedMediaId, onSelect }: PostPickerProps) {
  const [media, setMedia] = useState<InstagramMedia[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (cursor?: string) => {
      if (!accountId) return;
      cursor ? setLoadingMore(true) : setLoading(true);
      setError(null);
      try {
        const query = cursor ? `?limit=24&after=${encodeURIComponent(cursor)}` : "?limit=24";
        const data = await api.get<InstagramMediaResponse>(
          `/instagram/accounts/${accountId}/media${query}`
        );
        setMedia((current) => (cursor ? [...current, ...data.media] : data.media));
        setNextCursor(data.next_cursor || null);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Could not load posts from Instagram. Check the account connection."
        );
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [accountId]
  );

  useEffect(() => {
    setMedia([]);
    setNextCursor(null);
    load();
  }, [load]);

  if (!accountId) {
    return (
      <p className="rounded-lg border border-line bg-white p-4 text-sm font-medium text-muted">
        Select an Instagram account first to choose a post.
      </p>
    );
  }

  if (loading) {
    return (
      <p className="rounded-lg border border-line bg-white p-4 text-sm font-medium text-muted">
        Loading posts from Instagram...
      </p>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
        <p className="text-sm font-semibold text-amber-800">{error}</p>
        <Button type="button" variant="secondary" className="mt-3" onClick={() => load()}>
          Retry
        </Button>
      </div>
    );
  }

  if (media.length === 0) {
    return (
      <p className="rounded-lg border border-line bg-white p-4 text-sm font-medium text-muted">
        No posts found on this Instagram account.
      </p>
    );
  }

  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        {media.map((item) => {
          const isSelected = selectedMediaId === item.media_id;
          return (
            <button
              key={item.media_id}
              type="button"
              onClick={() => onSelect(item)}
              className={`group overflow-hidden rounded-lg border text-left transition ${
                isSelected
                  ? "border-accent ring-2 ring-accent/40"
                  : "border-line hover:border-accent/50"
              }`}
            >
              <div className="relative aspect-square bg-slate-100">
                {item.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={item.thumbnail_url}
                    alt={item.label}
                    className="h-full w-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-xs font-medium text-muted">
                    No preview
                  </div>
                )}
                {isSelected ? (
                  <span className="absolute right-2 top-2 rounded-full bg-accent px-2 py-0.5 text-xs font-bold text-white">
                    Selected
                  </span>
                ) : null}
              </div>
              <div className="grid gap-1 p-2">
                <span className="text-xs font-bold text-ink">
                  {mediaTypeLabel(item.media_type)}
                </span>
                <span className="line-clamp-2 text-xs font-medium text-muted">
                  {item.label}
                </span>
              </div>
            </button>
          );
        })}
      </div>
      {nextCursor ? (
        <Button
          type="button"
          variant="secondary"
          className="justify-self-start"
          disabled={loadingMore}
          onClick={() => load(nextCursor)}
        >
          {loadingMore ? "Loading..." : "Load more posts"}
        </Button>
      ) : null}
    </div>
  );
}
