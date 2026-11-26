"use client";

import { useParams } from "next/navigation";

import { CampaignForm } from "@/lib/many-instagram/campaign-form";
import { staffGet } from "@/lib/many-instagram/calls";
import type { Campaign } from "@/lib/many-instagram/types";
import { PageState } from "@/lib/page-state";
import { useManyData } from "@/lib/use-many";
import { LinkButton, PageHeader } from "@/lib/ui";

import "@/app/instagram-screen.css";

/** Edit one Instagram campaign (platform staff). */
export default function EditInstagramCampaignPage() {
  const { id } = useParams<{ id: string }>();
  const { data, status } = useManyData(
    () => staffGet<Campaign>(`/campaigns/${encodeURIComponent(id)}`),
    id,
  );
  return (
    <div className="ig-page">
      <PageHeader
        title={
          data ? <span dir="auto">{`Edit ${data.name}`}</span> : "Edit campaign"
        }
        actions={
          <LinkButton href={`/platform/instagram/campaigns/${id}/stats`}>
            Stats
          </LinkButton>
        }
      />
      <PageState status={status} homeHref="/platform/instagram/campaigns">
        {data && <CampaignForm key={data.id} campaign={data} />}
      </PageState>
    </div>
  );
}
