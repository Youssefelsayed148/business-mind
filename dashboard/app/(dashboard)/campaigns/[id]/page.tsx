"use client";

import { useEffect, useState } from "react";
import { CampaignForm } from "@/components/campaigns/CampaignForm";
import { DataState } from "@/components/ui/DataState";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import type { Campaign } from "@/lib/types";

export default function CampaignDetailPage({ params }: { params: { id: string } }) {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<Campaign>(`/campaigns/${params.id}`)
      .then(setCampaign)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load campaign"))
      .finally(() => setLoading(false));
  }, [params.id]);

  return (
    <div className="grid gap-6">
      <PageHeader title={campaign ? `Edit ${campaign.name}` : "Edit Campaign"} />
      <DataState loading={loading} error={error} />
      {campaign ? <CampaignForm campaign={campaign} /> : null}
    </div>
  );
}
