import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Northgrove Timelapse',
  description: 'Tracking progress of our house build',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
