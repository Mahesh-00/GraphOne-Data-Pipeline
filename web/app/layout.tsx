import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'GraphOne Intelligence Platform',
  description: 'AI & Venture Ecosystem Intelligence Graph Pipeline',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0B0F19] text-slate-100 antialiased selection:bg-blue-600 selection:text-white">
        {children}
      </body>
    </html>
  );
}

