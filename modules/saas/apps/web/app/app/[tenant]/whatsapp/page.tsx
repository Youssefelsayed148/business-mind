import { redirect } from "next/navigation";

export default async function WhatsappIndex({
  params,
}: {
  params: Promise<{ tenant: string }>;
}) {
  const { tenant } = await params;
  redirect(`/app/${encodeURIComponent(tenant)}/whatsapp/contacts`);
}
