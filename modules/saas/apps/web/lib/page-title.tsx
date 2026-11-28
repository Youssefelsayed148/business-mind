"use client";

import { usePathname } from "next/navigation";

const ROUTES: [RegExp, string][] = [
  [/^\/platform\/many$/, "Many overview"],
  [/^\/platform\/leads$/, "Leads"],
  [/^\/platform\/messages$/, "Messages"],
  [/^\/platform\/logs$/, "Logs"],
  [/^\/platform\/instagram\/accounts$/, "Instagram accounts"],
  [/^\/platform\/instagram\/campaigns\/new$/, "New Instagram campaign"],
  [
    /^\/platform\/instagram\/campaigns\/[^/]+\/stats$/,
    "Instagram campaign stats",
  ],
  [/^\/platform\/instagram\/campaigns\/[^/]+$/, "Instagram campaign"],
  [/^\/platform\/instagram\/campaigns$/, "Instagram campaigns"],
  [/^\/platform\/instagram\/conversations$/, "Instagram conversations"],
  [/\/whatsapp\/contacts$/, "WhatsApp contacts"],
  [/\/whatsapp\/templates$/, "WhatsApp templates"],
  [/\/whatsapp\/campaigns\/new$/, "New WhatsApp campaign"],
  [/\/whatsapp\/campaigns\/[^/]+$/, "WhatsApp campaign"],
  [/\/whatsapp\/campaigns$/, "WhatsApp campaigns"],
  [/\/whatsapp\/health$/, "WhatsApp health"],
  [/\/facebook\/campaigns$/, "Facebook campaigns"],
  [/^\/opt-in\/[^/]+$/, "Confirm WhatsApp messages"],
  [/^\/moved$/, "Page moved"],
  [/^\/accounts$/, "Accounts"],
  [/^\/platform\/members\/[^/]+$/, "Member details"],
  [/^\/platform\/members$/, "Members"],
  [/^\/$/, "Welcome"],
  [/^\/login$/, "Sign in"],
  [/^\/privacy$/, "Privacy"],
  [/^\/terms$/, "Terms of use"],
  [/^\/register$/, "Create account"],
  [/^\/accept-invite$/, "Accept invitation"],
  [/^\/widget\/sample$/, "Widget sample"],
  [/^\/widget\/frame$/, "Chat"],
  [/^\/platform\/clients\/[^/]+$/, "Organization details"],
  [/^\/platform\/operations$/, "Platform operations"],
  [/^\/platform\/change-requests$/, "Change requests"],
  [/^\/platform$/, "Organizations"],
  [/^\/app$/, "Workspaces"],
  [/^\/app\/[^/]+$/, "Overview"],
  [/\/settings\/members$/, "Team"],
  [/\/settings\/data$/, "Data and audit"],
  [/\/settings\/requests$/, "Request a change"],
  [/\/inbox\/[^/]+$/, "Conversation · Inbox"],
  [/\/inbox$/, "Inbox"],
  [/\/contacts\/links$/, "People across channels"],
  [/\/contacts\/[^/]+$/, "Contact details"],
  [/\/contacts$/, "Contacts"],
  [/\/analytics$/, "Insights"],
  [/\/conversations\/[^/]+$/, "Conversation"],
  [/\/conversations$/, "Conversations"],
  [/\/bots$/, "Bots"],
  [/\/overview$/, "Bot overview"],
  [/\/knowledge$/, "Knowledge"],
  [/\/playground$/, "Playground"],
  [/\/settings$/, "Bot settings"],
  [/\/install$/, "Install"],
  [/\/channels$/, "Channels"],
];

export default function PageTitle() {
  const pathname = usePathname();
  const label = ROUTES.find(([pattern]) => pattern.test(pathname))?.[1];
  return (
    <title>
      {label ? `${label} · Website Chatbot SaaS` : "Website Chatbot SaaS"}
    </title>
  );
}
