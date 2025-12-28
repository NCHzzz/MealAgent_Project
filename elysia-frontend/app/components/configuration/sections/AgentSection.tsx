"use client";

import React from "react";
import { RiRobot2Line } from "react-icons/ri";
import { SiDocsify } from "react-icons/si";
import {
  SettingCard,
  SettingHeader,
  SettingGroup,
  SettingItem,
  SettingTitle,
} from "../SettingComponents";
import SettingTextarea from "../SettingTextarea";
import SettingCheckbox from "../SettingCheckbox";
import { BackendConfig } from "@/app/types/objects";

interface AgentSectionProps {
  currentUserConfig: BackendConfig | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onUpdateFields: (key: string, value: any) => void;
  onUpdateSettings: (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    keyOrUpdates: string | Record<string, any>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    value?: any
  ) => void;
  title?: string; // Optional title override
  showDocumentation?: boolean; // Option to hide documentation button
  showFeedbackSetting?: boolean; // Option to show/hide feedback setting
}

/**
 * Component for configuring AI agent settings
 * Handles agent description, end goal, style, and feedback options
 */
export default function AgentSection({
  currentUserConfig,
  onUpdateFields,
  onUpdateSettings,
  title = "Agent",
  showDocumentation = true,
  showFeedbackSetting = true,
}: AgentSectionProps) {
  return (
    <SettingCard>
      <SettingHeader
        icon={<RiRobot2Line />}
        className="bg-highlight"
        header={title}
        buttonIcon={showDocumentation ? <SiDocsify /> : undefined}
        buttonText={showDocumentation ? "Tài liệu" : undefined}
        onClick={
          showDocumentation
            ? () => {
                window.open("https://weaviate.github.io/elysia/", "_blank");
              }
            : undefined
        }
      />

      <SettingGroup>
        <SettingItem>
          <SettingTitle
            title="Mô tả"
            description="Mô tả về agent của bạn."
          />
          <SettingTextarea
            value={currentUserConfig?.agent_description || ""}
            onChange={(value) => {
              onUpdateFields("agent_description", value);
            }}
          />
        </SettingItem>

        <SettingItem>
          <SettingTitle
            title="Mục tiêu cuối"
            description="Mục tiêu cuối của agent của bạn."
          />
          <SettingTextarea
            value={currentUserConfig?.end_goal || ""}
            onChange={(value) => {
              onUpdateFields("end_goal", value);
            }}
          />
        </SettingItem>

        <SettingItem>
          <SettingTitle title="Phong cách" description="Phong cách của agent của bạn." />
          <SettingTextarea
            value={currentUserConfig?.style || ""}
            onChange={(value) => {
              onUpdateFields("style", value);
            }}
          />
        </SettingItem>

        {showFeedbackSetting && (
          <SettingItem>
            <SettingTitle
              title="Cải thiện theo thời gian"
              description="Tự động sử dụng mô hình phức tạp cho tất cả tác vụ, trừ khi có đủ ví dụ phản hồi tích cực trước đó được tạo bởi mô hình phức tạp, trong trường hợp đó tác vụ sẽ sử dụng mô hình cơ bản. Nếu sử dụng tùy chọn này, bạn nên đưa ra phản hồi sau mỗi tương tác thành công."
            />
            <SettingCheckbox
              value={currentUserConfig?.settings.USE_FEEDBACK || false}
              onChange={(value) => {
                onUpdateSettings("USE_FEEDBACK", value);
              }}
            />
          </SettingItem>
        )}
      </SettingGroup>
    </SettingCard>
  );
}
