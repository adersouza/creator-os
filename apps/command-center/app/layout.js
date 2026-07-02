import "./globals.css";
import { Archivo, Spline_Sans_Mono } from "next/font/google";

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  display: "swap",
});

const splineSansMono = Spline_Sans_Mono({
  subsets: ["latin"],
  variable: "--font-spline-sans-mono",
  display: "swap",
});

export const metadata = {
  title: "Creator OS — Master Control",
  description: "Operator command center for the Creator OS content pipeline",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${archivo.variable} ${splineSansMono.variable}`}>
      <body className="antialiased stage-floor min-h-screen">{children}</body>
    </html>
  );
}
