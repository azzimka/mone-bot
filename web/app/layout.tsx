import type { Metadata, Viewport } from "next";
import Script from "next/script";
import "./globals.css";
import "./entry.css";

export const metadata: Metadata = {
  title: "Mone — shaxsiy moliya kabineti",
  description:
    "Kirim, chiqim va moliyaviy odatlaringizni bir joyda boshqaring.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="uz">
      <head>
        <Script
          src="https://telegram.org/js/telegram-web-app.js"
          strategy="beforeInteractive"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
