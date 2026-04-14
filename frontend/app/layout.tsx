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
          colorDanger: "#ef4444",
          borderRadius: "0.75rem",
          fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
          fontSize: "14px",
        },
        elements: {
          rootBox: { width: "100%" },
          card: {
            backgroundColor: "#18181b",
            border: "1px solid #27272a",
            boxShadow: "0 25px 50px -12px rgba(0,0,0,0.5)",
            borderRadius: "1rem",
          },
          headerTitle: { color: "#fafafa", fontSize: "18px", fontWeight: 600 },
          headerSubtitle: { color: "#a1a1aa" },
          formButtonPrimary: {
            backgroundColor: "#3b82f6",
            color: "#ffffff",
            borderRadius: "0.75rem",
            fontWeight: 500,
            fontSize: "14px",
            height: "40px",
          },
          formFieldInput: {
            backgroundColor: "#09090b",
            border: "1px solid #27272a",
            color: "#fafafa",
            borderRadius: "0.75rem",
            height: "40px",
          },
          formFieldLabel: { color: "#a1a1aa", fontSize: "13px" },
          footerActionLink: { color: "#3b82f6" },
          identityPreview: { backgroundColor: "#09090b", border: "1px solid #27272a" },
          identityPreviewText: { color: "#fafafa" },
          identityPreviewEditButton: { color: "#3b82f6" },
          dividerLine: { backgroundColor: "#27272a" },
          dividerText: { color: "#71717a" },
          socialButtonsBlockButton: {
            backgroundColor: "#09090b",
            border: "1px solid #27272a",
            color: "#fafafa",
            borderRadius: "0.75rem",
            height: "40px",
          },
          socialButtonsBlockButtonText: { color: "#fafafa", fontSize: "13px" },
          otpCodeFieldInput: {
            backgroundColor: "#09090b",
            border: "1px solid #27272a",
            color: "#fafafa",
          },
          formFieldInputShowPasswordButton: { color: "#71717a" },
          footer: { backgroundColor: "transparent" },
          footerAction: { backgroundColor: "transparent" },
          footerActionText: { color: "#71717a" },
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
