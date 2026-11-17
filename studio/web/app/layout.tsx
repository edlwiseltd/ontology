import type { Metadata } from "next";
import "./globals.css";
import "@/runtime/runtime.css";

export const metadata: Metadata = {
  title: "Autology Studio",
  description: "Design workbench for governed Autology use cases",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
