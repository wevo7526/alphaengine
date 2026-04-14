export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Override the main layout — no sidebar, full screen centered
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-bg-primary">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-text-primary mb-2">
          alpha<span className="text-accent">engine</span>
        </h1>
        <p className="text-sm text-text-tertiary mb-8">
          AI-Powered Quantitative Trading Intelligence
        </p>
        {children}
      </div>
    </div>
  );
}
