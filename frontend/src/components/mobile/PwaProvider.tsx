"use client";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{outcome: string}> };
export function PwaProvider() {
  const { t } = useTranslation("modules");
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  const [install, setInstall] = useState<InstallEvent | null>(null);
  const [offline, setOffline] = useState(false); const [error, setError] = useState(false);
  useEffect(() => {
    const online = () => setOffline(!navigator.onLine); online();
    const prompt = (event: Event) => { event.preventDefault(); setInstall(event as InstallEvent); };
    window.addEventListener("beforeinstallprompt", prompt); window.addEventListener("online", online); window.addEventListener("offline", online);
    let stopped = false;
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) void navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).then(reg => {
      if (stopped) return;
      if(reg.waiting) setWaiting(reg.waiting);
      reg.addEventListener("updatefound", () => { const worker = reg.installing;
        worker?.addEventListener("statechange", () => { if(worker.state === "installed" && navigator.serviceWorker.controller) setWaiting(worker); }); });
    }).catch(() => setError(true));
    return () => { stopped = true; window.removeEventListener("beforeinstallprompt", prompt); window.removeEventListener("online", online); window.removeEventListener("offline", online); };
  }, []);
  return <div className="pwaBar" aria-live="polite">
    {offline && <Link href="/mobile/offline">{t("mobile.offlineBanner")}</Link>}
    {install && <button className="secondaryButton" onClick={async () => { await install.prompt(); await install.userChoice; setInstall(null); }}>{t("mobile.install")}</button>}
    {waiting && <span>{t("mobile.updateReady")} <button className="secondaryButton" onClick={() => { waiting.postMessage({type: "ACTIVATE_UPDATE"}); setWaiting(null); }}>{t("mobile.update")}</button></span>}
    {error && <span>{t("mobile.offlineUnavailable")}</span>}
  </div>;
}
