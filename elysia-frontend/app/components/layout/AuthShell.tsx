"use client";

import React, { useContext } from "react";
import SidebarComponent from "../navigation/SidebarComponent";
import { SidebarTrigger } from "@/components/ui/sidebar";
import StartDialog from "../dialog/StartDialog";
import { AuthContext } from "../contexts/AuthContext";
import AuthPage from "@/app/pages/AuthPage";

const AuthShell = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated, loading } = useContext(AuthContext);

  if (loading) {
    return (
      <main className="flex flex-1 min-w-0 flex-col items-center justify-center p-6">
        <p className="text-secondary animate-pulse">Loading session...</p>
      </main>
    );
  }

  if (!isAuthenticated) {
    return (
      <main className="flex flex-1 min-w-0 flex-col items-center justify-center overflow-auto p-4">
        <AuthPage />
      </main>
    );
  }

  return (
    <>
      <SidebarComponent />
      <main className="flex flex-1 min-w-0 flex-col md:flex-row w-full gap-1 sm:gap-2 md:gap-6 items-start justify-start p-1 sm:p-2 md:p-6 overflow-auto">
        <SidebarTrigger className="lg:hidden flex text-secondary hover:text-primary hover:bg-foreground_alt z-50" />
        <StartDialog />
        {children}
      </main>
    </>
  );
};

export default AuthShell;

