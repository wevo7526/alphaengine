import Link from "next/link";

export const metadata = { title: "Terms of Service | AlphaEngine" };

export default function TermsPage() {
  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <LegalNav title="TERMS" />
      <div className="max-w-[760px] mx-auto px-6 py-16">
        <h1 className="font-display text-[34px] font-semibold tracking-[-0.01em] mb-2">Terms of Service</h1>
        <p className="text-[12px] font-mono text-text-quaternary mb-10">Beta. Subject to change before general availability.</p>

        <Section title="1. What AlphaEngine is">
          AlphaEngine is computational tooling: a stateless service that runs
          quantitative math and language-model reasoning on data you supply, and
          returns a structured result. It is not a broker, an adviser, or a data
          vendor. Outputs are not a recommendation to buy or sell any security.
        </Section>
        <Section title="2. Not investment advice">
          Nothing produced by the service is investment, legal, tax, or accounting
          advice. You are solely responsible for your own trading and investment
          decisions and for any outcomes that result from them.
        </Section>
        <Section title="3. Your data">
          You bring your own licensed data. On authenticated and paying paths the
          service operates in data-provided mode: it computes on the data in your
          request and discards it. We do not source, store, or redistribute that
          data. The demo and educational surfaces run on sample data for
          illustration only.
        </Section>
        <Section title="4. Beta service">
          The service is in beta and provided on an as-is basis without warranties.
          Availability, features, quotas, and pricing may change. We may suspend
          access for abuse, security, or quota reasons.
        </Section>
        <Section title="5. Acceptable use">
          Do not use the service to violate any law, infringe a data license, or
          attempt to exfiltrate other users&apos; data. Keys are per client and must
          be kept confidential.
        </Section>
        <Section title="6. Contact">
          Questions about these terms: reach us through the beta channel you were
          onboarded with.
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-[16px] font-semibold text-text-primary mb-2">{title}</h2>
      <p className="text-[14px] text-text-tertiary leading-[1.75]">{children}</p>
    </section>
  );
}

function LegalNav({ title }: { title: string }) {
  return (
    <header className="border-b border-border-primary/60 bg-bg-primary/85 backdrop-blur-lg sticky top-0 z-40">
      <div className="max-w-[1280px] mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          alpha<span className="text-brand">engine</span>
          <span className="ml-2 text-[11px] font-mono tracking-[0.18em] text-text-quaternary">/ {title}</span>
        </Link>
        <Link href="/" className="text-[12px] font-medium tracking-wide text-text-tertiary hover:text-text-primary transition-colors">← BACK</Link>
      </div>
    </header>
  );
}
