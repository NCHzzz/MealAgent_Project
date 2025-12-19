"use client";

import React, { useContext, useEffect, useState } from "react";

import { SocketContext } from "../contexts/SocketContext";

import { MdChatBubbleOutline } from "react-icons/md";
import { GoDatabase } from "react-icons/go";
import { AiOutlineExperiment } from "react-icons/ai";
import { FaCircle, FaSquareXTwitter } from "react-icons/fa6";
import { MdOutlineSettingsInputComponent } from "react-icons/md";
import { IoIosWarning } from "react-icons/io";

import HomeSubMenu from "@/app/components/navigation/HomeSubMenu";
import DataSubMenu from "@/app/components/navigation/DataSubMenu";
import EvalSubMenu from "@/app/components/navigation/EvalSubMenu";

import { CgFileDocument } from "react-icons/cg";

import { CgWebsite } from "react-icons/cg";
import { IoNewspaperOutline } from "react-icons/io5";
import { FaGithub } from "react-icons/fa";
import { FaLinkedin } from "react-icons/fa";
import { FaYoutube } from "react-icons/fa";
import { FaSignOutAlt } from "react-icons/fa";
import { GiMeal } from "react-icons/gi";

import { RiRobot2Line, RiCalendarTodoLine } from "react-icons/ri";
import { FiUser } from "react-icons/fi";
import { HiOutlineShoppingCart } from "react-icons/hi2";


import { public_path } from "@/app/components/host";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenuItem,
  SidebarMenu,
  SidebarMenuButton,
  SidebarHeader,
  SidebarFooter,
} from "@/components/ui/sidebar";

import { Separator } from "@/components/ui/separator";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import SettingsSubMenu from "./SettingsSubMenu";
import { RouterContext } from "../contexts/RouterContext";
import { CollectionContext } from "../contexts/CollectionContext";
import { SessionContext } from "../contexts/SessionContext";
import packageJson from "../../../package.json";
import { AuthContext } from "../contexts/AuthContext";
import { Button } from "@/components/ui/button";

const SidebarComponent: React.FC = () => {
  const { socketOnline } = useContext(SocketContext);
  const { changePage, currentPage } = useContext(RouterContext);
  const { collections, loadingCollections } = useContext(CollectionContext);
  const { unsavedChanges } = useContext(SessionContext);
  const { authUser, logout } = useContext(AuthContext);

  const [items, setItems] = useState<
    {
      title: string;
      mode: string[];
      icon: React.ReactNode;
      warning?: boolean;
      loading?: boolean;
      onClick: () => void;
    }[]
  >([]);

  useEffect(() => {
    const _items = [
      {
        title: "Chat",
        mode: ["chat"],
        icon: <MdChatBubbleOutline />,
        onClick: () => changePage("chat", {}, true, unsavedChanges),
      },
      {
        title: "Profile",
        mode: ["profile"],
        icon: <FiUser />,
        onClick: () => changePage("profile", {}, true, unsavedChanges),
      },
      {
        title: "Calendar",
        mode: ["mealHistory"],
        icon: <RiCalendarTodoLine />,
        onClick: () => changePage("mealHistory", {}, true, unsavedChanges),
      },
      {
        title: "Pantry",
        mode: ["pantry"],
        icon: <GiMeal />,
        onClick: () => changePage("pantry", {}, true, unsavedChanges),
      },
      {
        title: "Shopping List",
        mode: ["shopping"],
        icon: <HiOutlineShoppingCart />,
        onClick: () => changePage("shopping", {}, true, unsavedChanges),
      },
      {
        title: "Data",
        mode: ["data", "collection"],
        icon: !collections?.some((c) => c.processed === true) ? (
          <IoIosWarning className="text-warning" />
        ) : (
          <GoDatabase />
        ),
        warning: !collections?.some((c) => c.processed === true),
        loading: loadingCollections,
        onClick: () => changePage("data", {}, true, unsavedChanges),
      },
      {
        title: "Settings",
        mode: ["settings", "elysia"],
        icon: <MdOutlineSettingsInputComponent />,
        onClick: () => changePage("settings", {}, true, unsavedChanges),
      },
      
      {
        title: "Evaluation",
        mode: ["eval", "feedback", "display"],
        icon: <AiOutlineExperiment />,
        onClick: () => changePage("eval", {}, true, unsavedChanges),
      },
    ];
    setItems(_items);
  }, [collections, unsavedChanges]);

  const openNewTab = (url: string) => {
    window.open(url, "_blank");
  };

  return (
    <Sidebar className="fade-in border-r border-secondary/20 mr-2 md:mr-4 lg:mr-6">
      <SidebarHeader>
        <div className={`flex items-center gap-2 w-full justify-between p-2`}>
          <div className="flex items-center gap-2">
            <GiMeal className="w-6 h-6 text-accent" />
            <p className="text-sm font-bold text-primary">MealAgent</p>
          </div>
          <div className="flex items-center justify-center gap-1">
            {socketOnline ? (
              <div className="flex items-center gap-1.5">
                <FaCircle className="text-xs text-emerald-400 animate-pulse" />
                <span className="text-xs text-gray-500 font-small">Online</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5">
                <FaCircle className="text-xs text-red-400 animate-pulse" />
                <span className="text-xs text-gray-500 font-small">Offline</span>
              </div>
            )}
            <div className="flex flex-col items-end">
              <p className="text-xs text-muted-foreground">
                v{packageJson.version}
              </p>
            </div>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    variant={
                      item.mode.includes(currentPage)
                        ? "active"
                        : item.warning
                          ? "warning"
                          : "default"
                    }
                    onClick={item.onClick}
                  >
                    <p className="flex items-center gap-2">
                      {item.loading ? (
                        <FaCircle
                          scale={0.2}
                          className="text-lg pulsing_color"
                        />
                      ) : item.warning ? (
                        <IoIosWarning className="text-warning" />
                      ) : (
                        item.icon
                      )}
                      <span>{item.title}</span>
                    </p>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <Separator />

        {currentPage === "chat" && <HomeSubMenu />}
        {(currentPage === "data" || currentPage === "collection") && (
          <DataSubMenu />
        )}
        {(currentPage === "eval" ||
          currentPage === "feedback" ||
          currentPage === "display") && <EvalSubMenu />}
        {(currentPage === "settings" || currentPage === "elysia") && (
          <SettingsSubMenu />
        )}
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          {authUser && (
            // <SidebarMenuItem>
            //   <div className="w-full border border-accent/20 rounded-lg p-3 bg-background_alt">
            //     <p className="text-xs text-secondary uppercase">Signed in as</p>
            //     <p className="text-sm font-semibold truncate">
            //       {authUser.display_name || authUser.email}
            //     </p>
            //     <Button
            //       variant="outline"
            //       size="sm"
            //       className="mt-2 w-full hover:bg-accent hover:text-background"
            //       onClick={logout}
            //     >
            //       Logout
            //     </Button>
            //   </div>
            // </SidebarMenuItem>
            <SidebarMenuItem>
            <SidebarMenuButton
              className="w-full justify-start items-center"
              onClick={logout}
            >
              <FaSignOutAlt />
              <span>Log Out</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          )}
          {/* <SidebarMenuItem>
            <SidebarMenuButton
              className="w-full justify-start items-center"
              onClick={() => openNewTab("https://weaviate.github.io/elysia/")}
            >
              <CgFileDocument />
              <span>Documentation</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              className="w-full justify-start items-center"
              onClick={() => openNewTab("https://github.com/weaviate/elysia")}
            >
              <FaGithub />
              <span>Github</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <div className="flex items-center gap-2 px-2 py-2 text-xs text-secondary">
              <GiMeal className="w-4 h-4 text-accent" />
              <p>MealAgent - Smart Nutrition</p>
            </div>
          </SidebarMenuItem> */}
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
};

export default SidebarComponent;
