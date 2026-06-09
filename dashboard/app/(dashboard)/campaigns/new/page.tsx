import { CampaignForm } from "@/components/campaigns/CampaignForm";
import { PageHeader } from "@/components/ui/PageHeader";

export default function NewCampaignPage() {
  return (
    <div className="grid gap-6">
      <PageHeader title="New Campaign" />
      <CampaignForm />
    </div>
  );
}
