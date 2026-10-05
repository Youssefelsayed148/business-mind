import { WhatsappShell } from "@/components/whatsapp/WhatsappShell";
export default function WhatsappLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <WhatsappShell>{children}</WhatsappShell>;
}
