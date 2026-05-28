import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "RAG Async",
  description: "Async distributed RAG",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
