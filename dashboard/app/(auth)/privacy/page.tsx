"use client";

import Link from "next/link";

const sections = [
  {
    title: "Information We Collect",
    content: [
      "Account credentials (email address, hashed password) required to access the platform.",
      "Instagram Business account data obtained through Meta OAuth, including your Instagram user ID, username, and access tokens.",
      "Campaign configurations, keyword triggers, message templates, and automation rules you create within the platform.",
      "Lead records generated when Instagram users interact with your campaigns.",
      "Audit logs of platform activity including logins, campaign changes, and message delivery outcomes.",
    ],
  },
  {
    title: "How We Use Your Information",
    content: [
      "To authenticate your access and maintain your session securely.",
      "To connect your Instagram Business account via Meta's official API and execute automation campaigns on your behalf.",
      "To deliver automated direct messages and private replies to Instagram users who trigger your configured keywords.",
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
    title: "Data Storage and Security",
    content: [
      "All data is stored on servers within the European Union and protected by TLS encryption in transit.",
      "Database credentials, access tokens, and secrets are encrypted using industry-standard algorithms.",
      "We implement rate limiting, audit logging, and access controls to protect your data from unauthorized access.",
      "We do not sell, rent, or share your personal data with third parties for advertising or marketing purposes.",
    ],
  },
  {
    title: "Data Retention",
    content: [
      "Account data is retained for the duration of your active account.",
      "Campaign logs and message delivery records are retained for 90 days by default.",
      "Upon account deletion, all personal data is removed within 30 days, except where retention is required by law.",
      "You may request deletion of your data at any time by contacting us.",
    ],
  },
  {
    title: "Your Rights",
    content: [
      "You have the right to access, correct, or delete your personal data at any time.",
      "You may export your lead records in CSV format from the Leads page.",
      "You may disconnect your Instagram account at any time from the Accounts page, which revokes our access immediately.",
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
            Last updated: June 2026
          </div>
          <h1 className="text-3xl font-bold text-[#0F172A] mb-3">Privacy Policy</h1>
          <p className="text-[#64748B] max-w-2xl leading-relaxed">
            ManyOsirisChat is an Instagram automation platform. This policy explains what data we collect,
            how we use it, and your rights as a user. We are committed to handling your data with care and transparency.
          </p>
        </div>
      </div>

      {/* Content */}
      <main className="mx-auto max-w-4xl px-6 py-12">
        <div className="space-y-10">
          {sections.map((section, index) => (
            <div key={index} className="group">
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
