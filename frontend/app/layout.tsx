import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Terminal de Inteligencia Global",
  description: "Perceber o mundo primeiro. Tomar decisoes depois.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt">
      <body>{children}</body>
    </html>
  );
}
