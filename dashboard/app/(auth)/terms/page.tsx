"use client";

import Link from "next/link";

// TODO(owner): unverified against the code -- there are no plan limits in the
// application (see "Account Responsibilities"), no self-service account deletion
// (see "Termination"), and the liability cap needs a legal check.
const sections = [
  {
    title: "Acceptance of Terms",
    content: [
      "By accessing or using ManyOsirisChat, you agree to be bound by these Terms of Service.",
      "If you do not agree to these terms, you may not use the platform.",
      "We reserve the right to update these terms at any time. Continued use of the platform constitutes acceptance of updated terms.",
    ],
  },
  {
    title: "Platform Description",
    content: [
      "ManyOsirisChat is an Instagram, Facebook, and WhatsApp automation platform that allows businesses to automate direct messages, private replies, and lead capture via Meta's official APIs.",
      "The platform connects to your Instagram Business, Facebook Page, and WhatsApp Business accounts through Meta's official OAuth and Embedded Signup flows and operates within Meta's permitted use policies.",
      "All automation features are built on Meta's official Graph API and WhatsApp Cloud API. We do not use unofficial or unsupported access methods for any connected platform.",
    ],
  },
  {
    title: "Permitted Use",
    content: [
      "You may use ManyOsirisChat solely for lawful business purposes in compliance with Meta's Platform Terms, Instagram's Community Guidelines, Facebook's Community Standards, and WhatsApp's Business Messaging Policy.",
      "You are responsible for all content sent through automated campaigns, including messages, keywords, and templates.",
      "You must not use the platform to send spam, unsolicited messages, or content that violates applicable laws or Meta's policies.",
      "You must not attempt to circumvent Instagram's, Facebook's, or WhatsApp's rate limits, terms of service, or any platform restrictions.",
      "You are responsible for obtaining any necessary consent from recipients of automated messages where required by applicable law, including WhatsApp's messaging opt-in requirements.",
    ],
  },
  {
    title: "Account Responsibilities",
    content: [
      "You are responsible for maintaining the confidentiality of your login credentials.",
      "You must notify us immediately of any unauthorized access to your account.",
      "You are responsible for all activity that occurs under your account.",
      "Each account may connect multiple Instagram, Facebook, and WhatsApp accounts.",
    ],
  },
  {
    title: "Meta Platform Compliance",
    content: [
      "Your use of ManyOsirisChat must comply with Meta's Platform Terms, API Terms, and Community Guidelines for every connected platform (Instagram, Facebook, and WhatsApp) at all times.",
      "We reserve the right to suspend or terminate your account if your use violates Meta's policies or puts our platform access at risk.",
      "Meta may revoke our API access at any time, which may affect platform functionality. We are not liable for service disruptions caused by Meta's decisions.",
      "You acknowledge that platform automation is subject to Meta's policies and that certain features may be restricted or discontinued based on Meta's terms.",
    ],
  },
  {
    title: "Data and Privacy",
    content: [
      "Our collection and use of your data is governed by our Privacy Policy, which is incorporated into these Terms by reference.",
      "You retain ownership of all data you input into the platform, including campaign content and lead records.",
      "By connecting your Instagram, Facebook, or WhatsApp account, you grant us permission to access and use your data as described in our Privacy Policy.",
      "You may export or delete your data at any time as described in the Privacy Policy.",
    ],
  },
  {
    title: "AI-Generated Replies",
    content: [
      "AI replies are optional and are only used where you enable them for a connected account and campaign. Conversation text and your business profile are sent to our AI provider to write each reply, as described in the Privacy Policy.",
      "AI-generated replies can be inaccurate or incomplete. You are responsible for the business profile and instructions you provide, for reviewing how replies perform, and for turning AI off where it is not appropriate.",
    ],
  },
  {
    title: "Service Availability",
    content: [
      "We strive to maintain high availability but do not guarantee uninterrupted access to the platform.",
      "We may perform maintenance, updates, or modifications that temporarily affect availability.",
      "We are not liable for losses resulting from service interruptions, API changes by Meta, or circumstances beyond our reasonable control.",
    ],
  },
  {
    title: "Limitation of Liability",
    content: [
      "ManyOsirisChat is provided 'as is' without warranties of any kind, express or implied.",
      "We are not liable for any indirect, incidental, or consequential damages arising from your use of the platform.",
      "Our total liability to you shall not exceed the amount paid by you in the 12 months preceding the claim.",
      "We are not responsible for the content of messages sent through your campaigns or outcomes of your automation strategies.",
    ],
  },
  {
    title: "Termination",
    content: [
      "You may terminate your account at any time by contacting us. You may disconnect any connected account yourself from the Accounts page.",
      "We may suspend or terminate your account for violation of these terms, Meta's policies, or for any other reason with reasonable notice.",
      "Upon termination, your access to the platform will cease and your data will be handled as described in the Privacy Policy.",
    ],
  },
  {
    title: "Contact",
    content: [
      "For questions about these Terms of Service, contact us at: legal@theosirislabs.com",
      "ManyOsirisChat is operated by Osiris Labs. Registered address available upon request.",
    ],
  },
];

export default function TermsPage() {
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
            <Link href="/privacy" className="hover:text-[#0F172A] transition-colors">Privacy Policy</Link>
            <Link href="/terms" className="font-medium text-[#10B981]">Terms of Service</Link>
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
          <h1 className="text-3xl font-bold text-[#0F172A] mb-3">Terms of Service</h1>
          <p className="text-[#64748B] max-w-2xl leading-relaxed">
            These terms govern your use of ManyOsirisChat. By using the platform you agree to these terms.
            Please read them carefully before connecting your Instagram, Facebook, or WhatsApp account or
            running campaigns.
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
            <Link href="/privacy" className="text-[#64748B] hover:text-[#0F172A] transition-colors">Privacy Policy</Link>
            <Link href="/terms" className="font-medium text-[#10B981]">Terms of Service</Link>
            <Link href="/overview" className="text-[#64748B] hover:text-[#0F172A] transition-colors">Back to Dashboard</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
