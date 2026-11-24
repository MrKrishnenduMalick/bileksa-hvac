import type { Metadata } from "next";
import "./globals.css";
import { DemoBanner } from "@/components/demo-banner";

export const metadata: Metadata = {
  title: { default: "BILEKSA HVAC — Your AI Receptionist", template: "%s · BILEKSA HVAC" },
  description:
    "Your HVAC Business. Your AI Receptionist. Never miss an important business call again.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <DemoBanner />
        {children}
      </body>
    </html>
  );
}
