"use client";

import React, { useEffect, useState } from "react";
import { FaCircle } from "react-icons/fa";
import { IoArrowUpCircleSharp, IoClose } from "react-icons/io5";
import { RiFlowChart } from "react-icons/ri";
import { FaTrash } from "react-icons/fa";
import CollectionSelection from "./components/CollectionSelection";
import { Button } from "@/components/ui/button";
import { TbSettings } from "react-icons/tb";
import StreamingIndicator from "./components/StreamingIndicator";

interface QueryInputProps {
  handleSendQuery: (query: string, route?: string, mimick?: boolean) => void;
  query_length: number;
  currentStatus: string;
  addDisplacement: (value: number) => void;
  addDistortion: (value: number) => void;
  selectSettings: () => void;
}

const QueryInput: React.FC<QueryInputProps> = ({
  handleSendQuery,
  query_length,
  currentStatus,
  addDisplacement,
  addDistortion,
  selectSettings,
}) => {
  const [query, setQuery] = useState("");

  const [route, setRoute] = useState<string>("");
  const [mimick, setMimick] = useState<boolean>(false);
  const [showRoute, setShowRoute] = useState<boolean>(false);

  const triggerQuery = (_query: string) => {
    if (_query.trim() === "" || currentStatus !== "") return;
    handleSendQuery(_query, route, mimick);
    setQuery("");
  };

  useEffect(() => {
    addDisplacement(0.035);
    addDistortion(0.02);
  }, [query]);

  return (
    <div className={`fixed bottom-8 gap-3 flex items-center justify-center flex-col transition-all duration-300 md:w-[60vw] lg:w-[40vw] w-full px-4 md:px-0 lg:px-0`}>
      <div className="w-full flex justify-between items-center gap-2 mb-2">
        {currentStatus != "" ? (
          <StreamingIndicator
            isStreaming={true}
            message={currentStatus}
            variant="default"
          />
        ) : (
          <div></div>
        )}
      </div>
      {showRoute && (
        <div className="w-full flex gap-2 bg-background_alt rounded-xl p-2 fade-in justify-between">
          <input
            className="flex-grow p-2 bg-transparent outline-none text-xs resize-none"
            value={route}
            placeholder="Enter a route: e.g. search/query/text_response"
            onChange={(e) => setRoute(e.target.value)}
          />
          <div className="flex gap-2">
            {mimick ? (
              <button
                className="btn text-accent"
                onClick={() => setMimick(false)}
              >
                <p className="text-xs">Disable Mimicking</p>
              </button>
            ) : (
              <button
                className="btn text-secondary"
                onClick={() => setMimick(true)}
              >
                <p className="text-xs">Enable Mimicking</p>
              </button>
            )}
            <button
              className="btn-round text-secondary rounded-full"
              onClick={() => setRoute("")}
              title="Clear route"
              aria-label="Clear route"
            >
              <FaTrash size={12} />
            </button>
            <button
              className="btn-round text-secondary rounded-full"
              onClick={() => setShowRoute(false)}
              title="Close route panel"
              aria-label="Close route panel"
            >
              <IoClose size={12} />
            </button>
          </div>
        </div>
      )}
      <div
        className={`w-full flex gap-2 rounded-xl text-primary placeholder:text-secondary`}
      >
        <div
          className={`flex w-full bg-background_alt border border-accent/20 p-2 rounded-xl items-center flex-col shadow-meal`}
        >
          <textarea
            placeholder={
              query_length != 0
                ? "Ask a follow up question..."
                : "What will you ask today?"
            }
            className={`w-full p-2 bg-transparent placeholder:text-secondary outline-none text-sm leading-tight min-h-[5vh] max-h-[10vh] rounded-xl flex items-center justify-center resize-none ${query_length === 0 ? 'pt-2' : 'pt-1.5'}`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                triggerQuery(query);
              }
            }}
          />
          <div className="flex justify-end gap-1 w-full">
            {process.env.NODE_ENV === "development" && (
              <Button
                variant="ghost"
                size={"icon"}
                className={`${
                  showRoute && !route
                    ? "text-primary"
                    : route
                      ? "text-accent"
                      : "text-secondary"
                }`}
                onClick={() => setShowRoute(!showRoute)}
              >
                <RiFlowChart size={16} />
              </Button>
            )}
            {query_length > 0 && (
              <Button
                variant="ghost"
                size={"icon"}
                onClick={() => selectSettings()}
              >
                <TbSettings size={16} />
              </Button>
            )}
            <CollectionSelection />
            <Button
              variant="accept"
              size={"icon"}
              onClick={() => triggerQuery(query)}
              className="hover:bg-accent hover:text-background"
            >
              <IoArrowUpCircleSharp size={16} />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default QueryInput;
