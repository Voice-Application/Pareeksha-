import type { Metadata } from "next";
import type { ReactNode } from "react";
import { GeistMono } from "geist/font/mono";
import { Familjen_Grotesk, IBM_Plex_Sans, Geologica } from "next/font/google";
import { Providers } from "@/components/providers";
import { AppShell } from "@/components/layout/app-shell";
import "./globals.css";

// Light is Cobalt (Familjen Grotesk over IBM Plex Sans); dark is Vantage (Geologica, sharpened corners at display sizes).
const familjen = Familjen_Grotesk({ subsets: ["latin"], weight: ["500", "600"], variable: "--font-familjen", display: "swap" });
const plex = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex", display: "swap" });
const geologica = Geologica({ subsets: ["latin"], axes: ["SHRP"], variable: "--font-geologica", display: "swap" });

export const metadata: Metadata = {
  title: "Pareeksha",
  description: "Voice-agent testing and call auditing",
};

// Runs before paint: stored choice, else the system preference. Keeps dark mode from flashing light.
const THEME_SCRIPT = `try{var t=localStorage.getItem("theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.classList.toggle("dark",t==="dark")}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${GeistMono.variable} ${familjen.variable} ${plex.variable} ${geologica.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
