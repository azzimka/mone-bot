import type { Metadata } from "next";
import "./globals.css";
import "./entry.css";

export const metadata: Metadata = {
  title: "Mone — shaxsiy moliya kabineti",
  description:
    "Kirim, chiqim va moliyaviy odatlaringizni bir joyda boshqaring.",
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="uz">
      <body>{children}</body>
    </html>
  );
}
