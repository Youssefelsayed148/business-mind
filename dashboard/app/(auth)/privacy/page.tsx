"use client";

import Link from "next/link";

const sections: Array<{ id?: string; title: string; content: string[] }> = [
  {
    "title": "Information we collect",
    "content": [
      "We collect login details, workspace membership, connected Instagram Business account, Facebook Page and WhatsApp Business identifiers, encrypted access tokens, campaign settings, customer identities and conversation content needed to provide your business messaging service.",
      "We also retain delivery outcomes, security and operational records. Please do not send sensitive information that is unnecessary for your support request."
    ]
  },
  {
    "title": "How we use information",
    "content": [
      "We connect business channels through Meta authorization, receive their webhooks, run business-configured campaigns and customer support conversations, and show leads, messages and delivery reports to authorized workspace members.",
      "Optional AI replies answer questions about the connected business using its instructions and knowledge. The service is a business support and lead follow-up tool, not a general-purpose AI assistant."
    ]
  },
  {
    "title": "Meta authorization and messaging",
    "content": [
      "Instagram Login requests instagram_business_basic, instagram_business_manage_messages and instagram_business_manage_comments. Facebook Page and WhatsApp permission grants depend on the business login configuration approved in Meta; we use those grants only for connected business channels.",
      "Meta access tokens remain encrypted in ManyOsirisChat. We do not pass them to the SaaS chatbot or its AI providers.",
      "Ordinary support replies use the applicable 24-hour customer service window. We do not use a human-agent tag to extend automated or AI messaging. WhatsApp messages outside an open service window require an approved template and applicable consent."
    ]
  },
  {
    "title": "Optional SaaS chatbot delegation",
    "content": [
      "If a business enables delegation, ManyOsirisChat forwards genuine customer messages and channel identifiers to the Osiris Labs SaaS chatbot. The SaaS chatbot acts as a processor for that business support service and operates its bot knowledge, inbox, human handoff and reply generation.",
      "Delegated data includes message text or an unsupported-message notice, customer and conversation identifiers, available contact details, campaign name and opening message context, delivery outcomes and connection health. The SaaS may send authorized agent or bot replies back through ManyOsirisChat for delivery by Meta.",
      "The SaaS stores a separate copy. Disabling delegation stops ordinary new forwarding; it does not by itself erase data already held in either application."
    ]
  },
  {
    "title": "AI processing",
    "content": [
      "Where enabled, recent conversation messages, business instructions and relevant knowledge may be sent to the AI provider configured for the service. Many native AI uses OpenAI; the delegated SaaS uses its configured provider. Messages may contain personal information supplied by customers.",
      "The business controls whether AI is appropriate, provides its business information, reviews reply quality and can arrange a human response. AI replies can be inaccurate. Do not include unnecessary personal or confidential information in business instructions."
    ]
  },
  {
    "title": "Storage, access and security",
    "content": [
      "We use access controls, encrypted access-token storage, audit records and HTTPS deployment controls to protect data. Authorized operators and the business access only the data needed for their roles.",
      "We do not sell customer data or share it for third-party advertising. Service processing may involve Meta, the SaaS chatbot and configured hosting or AI providers. We do not claim a hosting region or provider retention period without verifying the deployed service settings."
    ]
  },
  {
    "title": "Retention",
    "content": [
      "Campaigns, conversations and delivery records remain until the business or an authorized operator deletes them or an applicable retention process removes them. There is no universal automatic deletion period for every ManyOsirisChat record.",
      "Many delegation payloads are cleared when successfully sent or dropped; failed payloads are cleared after seven days and terminal delegation records after thirty days by the retention job. SaaS event payloads follow tenant retention and its event deduplication records are retained for at least thirty days.",
      "Raw webhook payloads and separately held SaaS data must be included in a verified erasure process. Operators track deletion requests and aim to complete verified requests within thirty days; we will explain identity checks, legal retention or other delays."
    ]
  },
  {
    "title": "Data deletion",
    "content": [
      "Disconnecting a channel stops its use but does not itself erase stored conversation history or all stored credentials. Revoking access in Meta can trigger a signed callback. Callback receipt and its status page confirm the request was received; they do not prove deletion is complete.",
      "For account or customer data deletion, email privacy@theosirislabs.com with the business you contacted and the affected channel. We verify the request and locate the correct workspace and identity before deleting data. Do not email passwords or access tokens.",
      "For delegated channels, operators must verify erasure in both ManyOsirisChat and the SaaS chatbot. Until the cross-application erasure flow is verified in the deployed systems, operators coordinate both steps. A queued request or event is never treated as completed deletion."
    ],
    "id": "data-deletion"
  },
  {
    "title": "Your choices and contact",
    "content": [
      "You can ask to access, correct or delete personal data, and can disconnect business channels from the dashboard. Business administrators can export available lead records and manage workspace permissions.",
      "Contact privacy@theosirislabs.com for privacy requests. ManyOsirisChat and the SaaS chatbot are operated by Osiris Labs. The connected business remains responsible for its customer messaging purpose, instructions and required consent."
    ]
  }
];

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-white">
      {/* Top bar */}
      <header className="border-b border-slate-200 bg-white sticky top-0 z-10">
        <div className="mx-auto max-w-4xl px-6 py-4 flex items-center justify-between">
          <Link href="/overview" className="flex items-center gap-3 group">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#0F172A]">
              <svg viewBox="0 0 24 24" className="h-4 w-4 text-[#10B981] fill-current">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9V8h2v8zm4 0h-2V8h2v8z"/>
              </svg>
            </div>
            <span className="text-sm font-semibold text-[#0F172A] group-hover:text-[#10B981] transition-colors">
              ManyOsirisChat
            </span>
          </Link>
          <div className="flex items-center gap-4 text-sm text-[#64748B]">
            <Link href="/privacy" className="font-medium text-[#10B981]">Privacy Policy</Link>
            <Link href="/terms" className="hover:text-[#0F172A] transition-colors">Terms of Service</Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <div className="border-b border-slate-200 bg-[#F8FAFC]">
        <div className="mx-auto max-w-4xl px-6 py-12">
          <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-[#ECFDF5] px-3 py-1 text-xs font-medium text-emerald-700 mb-4">
            <span className="h-1.5 w-1.5 rounded-full bg-[#10B981]" />
            Last updated: October 2026
          </div>
          <h1 className="text-3xl font-bold text-[#0F172A] mb-3">Privacy Policy</h1>
          <p className="text-[#64748B] max-w-2xl leading-relaxed">
            ManyOsirisChat is an Instagram, Facebook, and WhatsApp automation platform. This policy explains
            what data we collect, how we use it, and your rights as a user. We are committed to handling
            your data with care and transparency.
          </p>
        </div>
      </div>

      {/* Content */}
      <main className="mx-auto max-w-4xl px-6 py-12">
        <div className="space-y-10">
          {sections.map((section, index) => (
            <div key={index} id={section.id} className="group scroll-mt-24">
              <div className="flex items-start gap-4">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-emerald-200 bg-[#ECFDF5] text-xs font-bold text-emerald-700 mt-0.5">
                  {String(index + 1).padStart(2, "0")}
                </div>
                <div className="flex-1">
                  <h2 className="text-lg font-bold text-[#0F172A] mb-3">{section.title}</h2>
                  <ul className="space-y-2">
                    {section.content.map((item, i) => (
                      <li key={i} className="flex items-start gap-3 text-sm text-[#64748B] leading-relaxed">
                        <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[#10B981]" />
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              {index < sections.length - 1 && (
                <div className="mt-10 border-t border-slate-100" />
              )}
            </div>
          ))}
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-[#F8FAFC]">
        <div className="mx-auto max-w-4xl px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-sm text-[#64748B]">
            © {new Date().getFullYear()} Osiris Labs. All rights reserved.
          </p>
          <div className="flex items-center gap-6 text-sm">
            <Link href="/privacy" className="font-medium text-[#10B981]">Privacy Policy</Link>
            <Link href="/terms" className="text-[#64748B] hover:text-[#0F172A] transition-colors">Terms of Service</Link>
            <Link href="/overview" className="text-[#64748B] hover:text-[#0F172A] transition-colors">Back to Dashboard</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
