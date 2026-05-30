import Link from "next/link";

export const metadata = { title: "Privacy Policy | AlphaEngine" };

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      <LegalNav title="PRIVACY" />
      <div className="max-w-[760px] mx-auto px-6 py-16">
        <h1 className="font-display text-[34px] font-semibold tracking-[-0.01em] mb-2">Privacy Policy</h1>
        <p className="text-[12px] font-mono text-text-quaternary mb-10">Beta. The short version: we do not keep your data.</p>

        <Section title="The principle: no data, by design">
          The market and portfolio data you send on authenticated and paying paths
          is processed in the moment and discarded. We do not source it, store it,
          or redistribute it. There is no data at rest to leak.
        </Section>
        <Section title="What we do collect">
          Account identity from your sign-in provider (name, email) to operate your
          account, and stateless operational telemetry: request shapes, sizes,
          latency, and error codes. Telemetry never records the values inside your
          payloads.
        </Section>
        <Section title="The demo surface">
          The public demo and the demo desk run on sample data for testing and
          educational purposes. Nothing you do on the public demo is saved.
          Authenticated demo accounts are isolated per user.
        </Section>
        <Section title="Isolation">
          Every authenticated user&apos;s workspace is isolated. We do not expose one
          user&apos;s research, memos, or positions to another.
        </Section>
        <Section title="Third parties">
          We use an authentication provider for sign-in and a hosting provider to
          run the service. Our reasoning desk uses Claude. None of these receive
          your stored data, because we do not store it.
        </Section>
        <Section title="Contact">
          Privacy questions: reach us through the beta channel you were onboarded
          with.
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
