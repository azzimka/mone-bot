import type { Metadata, Viewport } from "next";
import { LanguageProvider } from "../components/language-provider";
import { CategoryProvider } from "../components/category-provider";
import Script from "next/script";
import "./globals.css";
import "./entry.css";
import "./language.css";
import "./mobile-focus.css";
import "./finance.css";

export const metadata: Metadata = {
  applicationName: "Mone",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Mone", statusBarStyle: "default" },
  icons: {
    icon: [
      { url: "/favicon.ico?v=mone-1", sizes: "16x16 32x32", type: "image/x-icon" },
      { url: "/favicon-32x32.png?v=mone-1", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16x16.png?v=mone-1", sizes: "16x16", type: "image/png" },
    ],
    shortcut: "/favicon.ico?v=mone-1",
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
  },
  // Next.js emits the modern mobile-web-app-capable tag; retain Apple's tag for iOS.
  other: { "apple-mobile-web-app-capable": "yes" },
  title: "Mone — shaxsiy moliya kabineti",
  description:
    "Kirim, chiqim va moliyaviy odatlaringizni bir joyda boshqaring.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#197c5b",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
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
      <body>
        <CategoryProvider><LanguageProvider>{children}</LanguageProvider></CategoryProvider>
      </body>
    </html>
  );
}
