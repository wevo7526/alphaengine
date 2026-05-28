import Link from "next/link";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-bg-primary overflow-y-auto py-10 px-4">
      {/* Ambient gradient orbs to match the landing page */}
      <div className="pointer-events-none absolute inset-0 z-0" aria-hidden="true">
        <div className="absolute -top-32 -left-32 w-[36rem] h-[36rem] rounded-full bg-accent/[0.06] blur-3xl" />
        <div className="absolute bottom-0 -right-40 w-[36rem] h-[36rem] rounded-full bg-signal-green/[0.04] blur-3xl" />
      </div>

      <div className="relative z-10 flex flex-col items-center w-full">
        <Link href="/" className="mb-8 group">
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary text-center group-hover:opacity-90 transition-opacity">
            alpha<span className="text-accent">engine</span>
          </h1>
          <p className="text-[13px] text-text-tertiary text-center mt-2">
            Sign up takes a minute. Your first memo runs in under ten.
          </p>
        </Link>
        <div className="w-full max-w-[420px]">{children}</div>
      </div>
    </div>
  );
}
