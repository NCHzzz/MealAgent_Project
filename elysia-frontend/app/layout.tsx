import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import { Manrope, Space_Grotesk } from "next/font/google";
import { SessionProvider } from "./components/contexts/SessionContext";
import { CollectionProvider } from "./components/contexts/CollectionContext";
import { ConversationProvider } from "./components/contexts/ConversationContext";
import { SocketProvider } from "./components/contexts/SocketContext";
import { EvaluationProvider } from "./components/contexts/EvaluationContext";
import { ToastProvider } from "./components/contexts/ToastContext";
import { AuthProvider } from "./components/contexts/AuthContext";

import { Toaster } from "@/components/ui/toaster";

import { GoogleAnalytics } from "@next/third-parties/google";

import { SidebarProvider } from "@/components/ui/sidebar";
import { RouterProvider } from "./components/contexts/RouterContext";
import { ProcessingProvider } from "./components/contexts/ProcessingContext";
import AuthShell from "./components/layout/AuthShell";

const space_grotesk = Space_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-text",
  weight: ["300", "400", "500", "600", "700"],
});

const manrope = Manrope({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-heading",
  weight: ["200", "300", "400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "MealAgent",
  description: "Your Smart Nutrition & Meal Planning Assistant",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <GoogleAnalytics gaId={process.env.NEXT_PUBLIC_G_KEY || ""} />
      <body
        className={`bg-background h-screen w-screen overflow-hidden ${space_grotesk.variable} ${manrope.variable} font-text antialiased flex`}
      >
        <Suspense fallback={<div>Loading...</div>}>
          <ToastProvider>
            <AuthProvider>
              <RouterProvider>
                <SessionProvider>
                  <CollectionProvider>
                    <ConversationProvider>
                      <SocketProvider>
                        <EvaluationProvider>
                          <ProcessingProvider>
                            <SidebarProvider>
                              <AuthShell>{children}</AuthShell>
                            </SidebarProvider>
                          </ProcessingProvider>
                          <Toaster />
                        </EvaluationProvider>
                      </SocketProvider>
                    </ConversationProvider>
                  </CollectionProvider>
                </SessionProvider>
              </RouterProvider>
            </AuthProvider>
          </ToastProvider>
        </Suspense>
      </body>
    </html>
  );
}
