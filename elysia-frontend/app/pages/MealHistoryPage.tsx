"use client";

import React, { useContext, useEffect, useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";

import { SocketContext } from "../components/contexts/SocketContext";
import { SessionContext } from "../components/contexts/SessionContext";
import { ConversationContext } from "../components/contexts/ConversationContext";
import { ChatProvider } from "../components/contexts/ChatContext";
import RenderChat from "../components/chat/RenderChat";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { IoRefresh } from "react-icons/io5";
import { MdChatBubbleOutline } from "react-icons/md";

export default function MealHistoryPage() {
  const { sendQuery, socketOnline } = useContext(SocketContext);
  const { id } = useContext(SessionContext);
  const {
    changeBaseToQuery,
    addTreeToConversation,
    addQueryToConversation,
    currentConversation,
    conversations,
    updateFeedbackForQuery,
    loadingConversation,
  } = useContext(ConversationContext);

  const [currentStatus, setCurrentStatus] = useState<string>("");
  const [hasSentInitial, setHasSentInitial] = useState<boolean>(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [currentQuery, setCurrentQuery] = useState<{
    [key: string]: import("../types/chat").Query;
  }>({});

  useEffect(() => {
    setCurrentQuery(
      currentConversation && conversations.length > 0
        ? conversations.find((c) => c.id === currentConversation)?.queries || {}
        : {}
    );
    setCurrentStatus(
      currentConversation && conversations.length > 0
        ? conversations.find((c) => c.id === currentConversation)?.current || ""
        : ""
    );
  }, [currentConversation, conversations]);

  useEffect(() => {
    if (
      socketOnline &&
      currentConversation &&
      !hasSentInitial &&
      Object.keys(currentQuery).length === 0 &&
      currentStatus === ""
    ) {
      const prompt =
        "Hiển thị lịch sử bữa ăn của tôi trong 30 ngày gần đây (meal_history_tool).";
      const query_id = uuidv4();

      const _conversation = conversations.find(
        (c) => c.id === currentConversation
      );

      if (_conversation) {
        sendQuery(
          id || "",
          prompt.trim(),
          _conversation.id,
          query_id,
          "",
          false
        );
        changeBaseToQuery(_conversation.id, prompt.trim());
        addTreeToConversation(_conversation.id);
        addQueryToConversation(_conversation.id, prompt.trim(), query_id);
        setHasSentInitial(true);
      }
    }
  }, [
    socketOnline,
    currentConversation,
    conversations,
    hasSentInitial,
    currentQuery,
    currentStatus,
    sendQuery,
    id,
    changeBaseToQuery,
    addTreeToConversation,
    addQueryToConversation,
  ]);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [currentQuery, currentStatus]);

  if (!socketOnline) {
    return (
      <div className="flex flex-col w-full h-full items-center justify-center">
        <p className="text-primary text-xl shine">Đang kết nối tới Elysia...</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col w-full h-full items-center justify-start gap-3">
      <div className="flex w-full justify-between items-center lg:sticky z-20 top-0 lg:p-0 p-4 gap-5 bg-background">
        <div className="flex flex-col gap-1">
          <p className="text-primary text-lg font-semibold">
            Lịch sử bữa ăn (30 ngày gần đây)
          </p>
          <p className="text-secondary text-xs">
            Trang này tự động gọi MealAgent để lấy log bữa ăn của bạn trong 1
            tháng gần nhất.
          </p>
        </div>
        <Button
          size="icon"
          variant="outline"
          onClick={() => {
            setHasSentInitial(false);
          }}
          disabled={currentStatus !== ""}
        >
          <IoRefresh />
        </Button>
      </div>

      <Separator className="w-full" />

      {loadingConversation && (
        <div className="flex w-full h-full justify-center items-center">
          <p className="text-primary text-xl shine">
            Đang tải hội thoại hiện tại...
          </p>
        </div>
      )}

      {!loadingConversation && (
        <div className="flex flex-col w-full max-h-[calc(100vh-120px)] overflow-y-auto justify-center items-center">
          <div className="flex flex-col w-full md:w-[60vw] lg:w-[40vw] h-[80vh] ">
            {currentQuery &&
              Object.entries(currentQuery)
                .sort((a, b) => a[1].index - b[1].index)
                .map(([queryId, query], index, array) => (
                  <ChatProvider key={queryId}>
                    <RenderChat
                      key={queryId + index}
                      messages={query.messages}
                      conversationID={currentConversation || ""}
                      queryID={queryId}
                      finished={query.finished}
                      query_start={query.query_start}
                      query_end={query.query_end}
                      _collapsed={index !== array.length - 1}
                      messagesEndRef={messagesEndRef}
                      NER={query.NER}
                      feedback={query.feedback}
                      updateFeedback={updateFeedbackForQuery}
                      addDisplacement={() => {}}
                      addDistortion={() => {}}
                      handleSendQuery={() => {}}
                      isLastQuery={index === array.length - 1}
                    />
                  </ChatProvider>
                ))}
            {currentQuery && Object.keys(currentQuery).length === 0 && (
              <div className="flex flex-col items-center justify-center w-full h-full gap-3">
                <MdChatBubbleOutline className="text-accent w-8 h-8" />
                <p className="text-primary text-sm">
                  Đang chuẩn bị truy vấn lịch sử bữa ăn của bạn...
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}


