/* eslint-disable */

"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ToastContext } from "./ToastContext";

export const RouterContext = createContext<{
  currentPage: string;
  changePage: (
    page: string,
    params?: Record<string, any>,
    replace?: boolean,
    guarded?: boolean
  ) => void;
}>({
  currentPage: "chat",
  changePage: () => { },
});

export const RouterProvider = ({ children }: { children: React.ReactNode }) => {
  const [currentPage, setCurrentPage] = useState<string>("chat");

  const { showConfirmModal } = useContext(ToastContext);

  const searchParams = useSearchParams();
  const router = useRouter();

  const changePage = (
    page: string,
    params: Record<string, any> = {},
    replace: boolean = false,
    guarded: boolean = false
  ) => {
    if (guarded) {
      showConfirmModal(
        "Unsaved Changes",
        "You have unsaved changes. Are you sure you want to leave this page? You will lose your changes.",
        () => changePageFunction(page, params, replace)
      );
      return;
    } else {
      changePageFunction(page, params, replace);
    }
  };

  const changePageFunction = (
    page: string,
    params: Record<string, any> = {},
    replace: boolean = false
  ) => {
    const nextParams = new URLSearchParams();

    if (!replace) {
      searchParams.forEach((value, key) => {
        if (key === "page") return;
        if (params[key] !== undefined && params[key] !== null) return;
        nextParams.set(key, value);
      });
    }

    if (page) {
      nextParams.set("page", page);
    }

    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null) {
        nextParams.delete(key);
        return;
      }
      nextParams.set(key, String(value));
    });

    const queryString = nextParams.toString();
    const url = queryString ? `/?${queryString}` : "/";

    if (replace) {
      router.replace(url, { scroll: false });
    } else {
      router.push(url, { scroll: false });
    }
    setCurrentPage(page);
  };

  useEffect(() => {
    // Get page from URL parameter
    const pageParam = searchParams.get("page");

    // If no page parameter exists, redirect to chat page
    if (!pageParam) {
      // Preserve any existing query parameters (like conversation)
      const currentParams: Record<string, any> = {};
      searchParams.forEach((value, key) => {
        currentParams[key] = value;
      });

      // Add page=chat to the URL
      const url = `/?${new URLSearchParams({ page: "chat", ...currentParams }).toString()}`;
      window.history.replaceState(null, "", url);
      setCurrentPage("chat");
      return;
    }

    // Validate page parameter against known pages
    const validPages = [
      "chat",
      "data",
      "collection",
      "settings",
      "eval",
      "feedback",
      "elysia",
      "display",
      "profile",
      "mealHistory",
      "pantry",
      "shopping",
      "recipeSubmission",
      "adminRecipe",
    ];
    const validatedPage = validPages.includes(pageParam) ? pageParam : "chat";

    // If invalid page, redirect to chat
    if (pageParam !== validatedPage) {
      const currentParams: Record<string, any> = {};
      searchParams.forEach((value, key) => {
        if (key !== "page") {
          currentParams[key] = value;
        }
      });

      const url = `/?${new URLSearchParams({ page: "chat", ...currentParams }).toString()}`;
      window.history.replaceState(null, "", url);
    }

    setCurrentPage(validatedPage);
  }, [searchParams]);

  return (
    <RouterContext.Provider
      value={{
        currentPage,
        changePage,
      }}
    >
      {children}
    </RouterContext.Provider>
  );
};
