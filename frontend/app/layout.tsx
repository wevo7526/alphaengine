import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { Providers } from "@/components/Providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Alpha Engine",
  description: "AI-Powered Quantitative Trading Intelligence",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider
      appearance={{
        variables: {
          colorPrimary: "#3b82f6",
          colorBackground: "#18181b",
          colorText: "#fafafa",
          colorTextSecondary: "#a1a1aa",
          colorInputBackground: "#09090b",
          colorInputText: "#fafafa",
          colorNeutral: "#fafafa",
          borderRadius: "0.75rem",
        },
        elements: {
          card: "bg-[#18181b] border border-[#27272a] shadow-2xl",
          headerTitle: "text-[#fafafa]",
          headerSubtitle: "text-[#a1a1aa]",
          formButtonPrimary: "bg-[#3b82f6] hover:bg-[#2563eb] text-white",
          footerActionLink: "text-[#3b82f6] hover:text-[#60a5fa]",
          identityPreview: "bg-[#09090b] border-[#27272a]",
          formFieldInput: "bg-[#09090b] border-[#27272a] text-[#fafafa]",
          formFieldLabel: "text-[#a1a1aa]",
          dividerLine: "bg-[#27272a]",
          dividerText: "text-[#71717a]",
          socialButtonsBlockButton: "bg-[#09090b] border-[#27272a] text-[#fafafa] hover:bg-[#27272a]",
          socialButtonsBlockButtonText: "text-[#fafafa]",
          otpCodeFieldInput: "bg-[#09090b] border-[#27272a] text-[#fafafa]",
        },
      }}
    >
      <html
        lang="en"
        className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      >
        <body className="h-full flex">
          <Providers>
            <Sidebar />
            <main className="flex-1 ml-52 flex flex-col min-h-screen">
              {children}
            </main>
          </Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
