import type { MetadataRoute } from "next";
export default function manifest(): MetadataRoute.Manifest {
  return { id: "/", name: "Vehicle Fleet Control", short_name: "Fleet Control", description: "Driver and technician workspace",
    start_url: "/mobile", scope: "/", display: "standalone", background_color: "#f3f6fa", theme_color: "#123544",
    icons: [{src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any"},
      {src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any"},
      {src: "/icons/icon-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable"}] };
}
