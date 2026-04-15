export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-bg-primary">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-text-primary text-center">
          alpha<span className="text-accent">engine</span>
        </h1>
        <p className="text-sm text-text-tertiary text-center mt-2">
          AI-Powered Quantitative Trading Intelligence
        </p>
      </div>
      <div className="w-full max-w-[400px] px-4">
        {children}
      </div>
    </div>
  );
}
