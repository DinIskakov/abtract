import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "abtract",
  description: "A/B testing for AI agents",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
