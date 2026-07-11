import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Seismograph — Frontier Intel",
  description: "Daily monitoring and impact analysis over where technology is built.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">{children}</body>
    </html>
  );
}
