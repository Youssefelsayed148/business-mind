"use client";

import { CampaignForm } from "@/lib/many-instagram/campaign-form";
import { PageHeader } from "@/lib/ui";

import "@/app/instagram-screen.css";

/** New Instagram campaign (platform staff). */
export default function NewInstagramCampaignPage() {
  return (
    <div className="ig-page">
      <PageHeader
        title="New campaign"
        purpose="Set up a comment-triggered message campaign. It starts as a draft."
      />
      <CampaignForm />
    </div>
  );
}
