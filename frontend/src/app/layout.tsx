import type { Metadata } from "next";
import { Inter, Mukta, Noto_Sans_Devanagari } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

// Mukta covers Devanagari and Latin, so Nepali text never falls back to a system font.
const mukta = Mukta({
  variable: "--font-mukta",
  subsets: ["devanagari", "latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

// Offered in the editor's font menu; the renderer stores the plain family name.
const notoDevanagari = Noto_Sans_Devanagari({
  variable: "--font-noto-devanagari",
  subsets: ["devanagari", "latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "MAWAPRESS", template: "%s | MAWAPRESS" },
  description: "MAWAPRESS, the voice of Morang.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${mukta.variable} ${notoDevanagari.variable}`}
    >
      <body className="min-h-screen antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <TooltipProvider>{children}</TooltipProvider>
          <Toaster richColors closeButton />
        </ThemeProvider>
      </body>
    </html>
  );
}
