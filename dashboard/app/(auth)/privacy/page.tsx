"use client";

import Link from "next/link";

// TODO(owner): the claims below that depend on operations rather than code are
// unverified: EU hosting, 30-day deletion on request, the end-user deletion
// route, and OpenAI's own retention terms. Facebook permissions are set in the
// Meta dashboard config (backend/app/core/config.py also lists
// pages_manage_engagement); confirm the list matches the live config.
const sections: Array<{ id?: string; title: string; content: string[] }> = [
  {
    title: "Information We Collect",
    content: [
      "Account credentials (email address, hashed password) required to access the platform.",
      "Instagram Business account data obtained through Meta OAuth, including your Instagram user ID, username, and access tokens.",
      "Facebook Page data obtained through Facebook Login for Business, including your Page ID, Page name, commenter identifiers, and access tokens.",
      "WhatsApp Business data obtained through Meta's Embedded Signup, including your WhatsApp Business Account ID, phone number ID, and access tokens.",
      "Campaign configurations, keyword triggers, message templates, and automation rules you create within the platform.",
      "Lead records generated when Instagram, Facebook, or WhatsApp users interact with your campaigns.",
      "The content of direct messages and private replies exchanged with those users, stored so that conversations can be shown in your dashboard.",
      "Audit logs of platform activity including logins, campaign changes, and message delivery outcomes.",
    ],
  },
  {
    title: "How We Use Your Information",
    content: [
      "To authenticate your access and maintain your session securely.",
      "To connect your Instagram Business, Facebook Page, and WhatsApp Business accounts via Meta's official APIs and execute automation campaigns on your behalf.",
      "To deliver automated direct messages and private replies to Instagram and Facebook users, and automated replies to WhatsApp users, who trigger your configured keywords or message your connected accounts.",
      "To generate leads, track campaign performance, and provide delivery reports within your dashboard.",
      "To maintain audit logs for security, compliance, and troubleshooting purposes.",
    ],
  },
  {
    title: "Meta and Instagram Data",
    content: [
      "We access your Instagram Business account solely through Meta's official Graph API using permissions you explicitly grant during OAuth.",
      "We request the following permissions: instagram_business_basic, instagram_business_manage_messages, instagram_business_manage_comments.",
      "Access tokens are encrypted at rest and are never shared with third parties.",
      "We only read and send messages as instructed by your campaign configurations. We do not access personal Instagram accounts.",
      "You may revoke our access at any time through your Instagram account settings or by disconnecting from the Accounts page.",
    ],
  },
  {
    title: "Facebook Page Data",
    content: [
      "We access your Facebook Page solely through Meta's official Graph API using permissions you explicitly grant during Facebook Login for Business.",
      "We request the following permissions: pages_show_list, pages_manage_metadata, pages_read_engagement, pages_messaging.",
      "We collect Page comments, commenter identifiers (ASID/PSID), and Messenger message content solely to deliver the private replies and automated DMs configured in your campaigns.",
      "Page access tokens are encrypted at rest and are never shared with third parties.",
      "We do not access personal Facebook profiles, friends lists, or any data outside your connected Page's own activity.",
      "You may revoke our access at any time through your Facebook Business settings or by disconnecting from the Accounts page.",
    ],
  },
  {
    title: "WhatsApp Business Data",
    content: [
      "We access your WhatsApp Business phone number solely through Meta's official WhatsApp Cloud API using permissions granted during Embedded Signup.",
      "We request the following permissions: whatsapp_business_messaging, whatsapp_business_management.",
      "We collect the WhatsApp Business Account ID, phone number ID, and message content solely to deliver the automated replies configured for your number.",
      "Access tokens are encrypted at rest and are never shared with third parties.",
      "You may revoke our access at any time through Meta Business Manager or by disconnecting from the Accounts page.",
    ],
  },
  {
    id: "ai-generated-replies",
    title: "AI-Generated Replies",
    content: [
      "AI-generated replies are optional and off by default. They are only used for an Instagram, Facebook, or WhatsApp account where the account owner has turned AI on, and for a campaign only when AI is also enabled on that campaign. Replying to people who message the business directly, outside any campaign, is a separate setting.",
      "When AI is used to write a reply, we send the following to our AI provider, OpenAI: the recent messages of that conversation (the customer's messages and the replies already sent), and instructions built from your business profile, tone instructions, business type, and the campaign name. We do not send the customer's username, profile, or account identifiers in these requests.",
      "OpenAI acts as a processor on our behalf, only to generate the reply. Replies are sent to the customer through Meta's APIs.",
      "You can switch AI off for any connected account or campaign at any time in the dashboard, which stops further messages from being sent to the AI provider for it. We can also disable AI for the whole platform.",
      "Do not put personal data or confidential information in your business profile or tone instructions, because that text is included in every AI request for the account.",
    ],
  },
  {
    title: "Data Storage and Security",
    content: [
      // TODO(owner): the previous text said all data is stored on servers within the
      // European Union. Nothing in the repository states the hosting region; confirm
      // it and restore the claim only if it is true.
      "Data is protected by TLS encryption in transit.",
      "Access tokens are encrypted at rest.",
      "We implement rate limiting, audit logging, and role-based access controls to protect your data from unauthorized access.",
      "We do not sell or rent your personal data, and we do not share it with third parties for advertising or marketing purposes. We share data only with Meta, through its official APIs, and with our AI provider as described under AI-Generated Replies.",
    ],
  },
  {
    title: "Data Retention",
    content: [
      "Account data is retained for the duration of your active account.",
      // TODO(owner): the previous text promised 90-day log retention, but no job in the
      // codebase purges logs or messages. Add a purge job before restoring a fixed period.
      "Campaign logs, conversations, and message delivery records are kept for as long as your account is active; we do not currently delete them automatically on a schedule.",
      "Upon account deletion, all personal data is removed within 30 days, except where retention is required by law.",
      "You may request deletion of your data at any time by contacting us.",
    ],
  },
  {
    id: "data-deletion",
    title: "Data Deletion",
    content: [
      "You may disconnect any connected Instagram, Facebook, or WhatsApp account at any time from the Accounts page — this immediately stops all automation for that account and we stop using its access token. You can also remove ManyOsirisChat from your Instagram, Facebook, or Meta Business settings to revoke the access you granted.",
      "To delete your ManyOsirisChat account entirely, contact us at the email below. All associated data — including leads, conversations, campaign configurations, and access tokens across every connected platform — is permanently deleted within 30 days, except where retention is required by law.",
      "You may also request deletion of specific data (e.g. lead records for one platform) without closing your account by contacting us with the details of your request.",
      // TODO(owner): confirm you can honour this route for end users; the app has no self-service deletion for them.
      "If you are a person who messaged a business that uses ManyOsirisChat and want your conversation data deleted, email privacy@theosirislabs.com with your Instagram, Facebook, or WhatsApp username or number and the business you contacted. We will delete the matching records within 30 days, except where retention is required by law.",
    ],
  },
  {
    title: "Your Rights",
    content: [
      "You have the right to access, correct, or delete your personal data at any time.",
      "You may export your lead records in CSV format from the Leads page.",
      "You may disconnect your Instagram, Facebook, or WhatsApp account at any time from the Accounts page, which stops automation for it immediately.",
      "For data requests or concerns, contact us at the email address listed below.",
    ],
  },
  {
    title: "Contact",
    content: [
      "For privacy-related questions or requests, contact us at: privacy@theosirislabs.com",
      "ManyOsirisChat is operated by Osiris Labs. Registered address available upon request.",
    ],
  },
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
