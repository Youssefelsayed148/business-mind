"use client";

import Link from "next/link";

const sections: Array<{ id?: string; title: string; content: string[] }> = [
  {
    "title": "Using the service",
    "content": [
      "By using ManyOsirisChat you agree to these terms and the Privacy Policy. The service connects a business's Instagram Business account, Facebook Page or WhatsApp Business number to its own campaigns and customer support workflow.",
      "You must use the service lawfully, comply with applicable Meta policies, and obtain consent where required. You are responsible for your business instructions, campaigns, templates and messages."
    ]
  },
  {
    "title": "Business support and AI",
    "content": [
      "Optional AI answers questions about the connected business using its configured information and knowledge. The service is not a general-purpose AI assistant. AI output can be wrong; the business must review its operation and provide human support when appropriate.",
      "Many native replies and optional SaaS chatbot delegation have separate settings. When delegation is enabled, the SaaS chatbot operates reply generation, inbox and handoff while ManyOsirisChat retains Meta credentials and message delivery."
    ]
  },
  {
    "title": "Messaging limits",
    "content": [
      "Support replies must respect the applicable 24-hour messaging window. Automated and AI replies must not use a human-agent tag to extend that window. WhatsApp messages outside an open service window require an approved template and applicable opt-in.",
      "Do not send spam, impersonate another business, evade rate limits or use the service for prohibited content. Meta may restrict or revoke access independently of us."
    ]
  },
  {
    "title": "Data and processors",
    "content": [
      "You retain your rights in business content and customer data. You authorize processing needed to provide the service under your instructions, including the Osiris Labs SaaS chatbot as processor when you enable delegation and configured AI/hosting providers as described in the Privacy Policy.",
      "Keep credentials secure, grant workspace access only to appropriate people and avoid unnecessary sensitive data in messages or business instructions."
    ]
  },
  {
    "title": "Deletion and termination",
    "content": [
      "You may disconnect channels in the dashboard and request account or customer data deletion at privacy@theosirislabs.com. Disconnecting a channel or disabling delegation is not deletion of stored records.",
      "Erasure requests require identity and scope checks, and delegated data requires confirmation from both applications. Operators aim to complete verified requests within thirty days and will explain exceptional delays. Callback receipt or queue acceptance is not completion.",
      "We may suspend access for misuse or legal or Meta policy obligations. Retained data is handled according to the Privacy Policy and applicable law."
    ]
  },
  {
    "title": "Availability and responsibility",
    "content": [
      "The service depends on Meta, hosting and configured AI providers and may be interrupted or changed. We do not guarantee uninterrupted access or accurate AI output.",
      "Nothing in these terms removes rights that applicable law does not allow us to limit. Commercial liability and service commitments are governed by any separate agreement with your business."
    ]
  },
  {
    "title": "Contact",
    "content": [
      "Contact legal@theosirislabs.com about these terms and privacy@theosirislabs.com about personal data. ManyOsirisChat is operated by Osiris Labs."
    ]
  }
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
