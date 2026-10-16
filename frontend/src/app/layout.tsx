import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Reel Studio AI — A studio for the moments that matter",
  description:
    "Turn educational recordings into short, captioned vertical reels with local-first AI processing.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
