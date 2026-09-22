import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";
import { LanguageProvider } from "@/components/i18n/LanguageProvider";

export const metadata: Metadata = {
  title: "Vehicle Fleet Control",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, statusBarStyle: "default", title: "Fleet Control" },
  icons: { apple: "/icons/apple-touch-icon.png" },
  description: "Fleet management system rebuilt with Next.js and FastAPI"
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover", themeColor: "#123544" };

const clearDevelopmentServiceWorker = `
  if ("serviceWorker" in navigator) {
    void (async () => {
      const isAppWorker = (worker) => worker && new URL(worker.scriptURL).pathname === "/sw.js";
      const hadAppController = isAppWorker(navigator.serviceWorker.controller);
      try {
        const registrations = await navigator.serviceWorker.getRegistrations();
        await Promise.all(registrations
          .filter((registration) => [registration.active, registration.waiting, registration.installing].some(isAppWorker))
          .map((registration) => registration.unregister()));
        if ("caches" in window) {
          await Promise.all((await caches.keys())
            .filter((name) => name.startsWith("vfc-shell-"))
            .map((name) => caches.delete(name)));
        }
      } finally {
        if (hadAppController && !sessionStorage.getItem("vfc-dev-sw-cleared")) {
          sessionStorage.setItem("vfc-dev-sw-cleared", "1");
          location.reload();
        }
      }
    })();
  }
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {process.env.NODE_ENV === "development" && <head><script dangerouslySetInnerHTML={{ __html: clearDevelopmentServiceWorker }} /></head>}
      <body>
        <LanguageProvider>
          <AppShell>{children}</AppShell>
        </LanguageProvider>
      </body>
    </html>
  );
}
