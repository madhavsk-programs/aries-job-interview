import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@livekit/components-styles";
import "./globals.css";


export const metadata: Metadata = {
  title: "ARIES Voice",
  description: "Voice-native adaptive interview practice.",
};


export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

