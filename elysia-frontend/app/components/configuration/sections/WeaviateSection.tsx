"use client";

import React from "react";
import { FaDatabase, FaCloud, FaServer } from "react-icons/fa";
import { BsDatabaseFillAdd } from "react-icons/bs";
import {
  SettingCard,
  SettingHeader,
  SettingGroup,
  SettingItem,
  SettingTitle,
  SettingToggle,
} from "../SettingComponents";
import SettingInput from "../SettingInput";
import WarningCard from "../WarningCard";
import { BackendConfig, FrontendConfig } from "@/app/types/objects";
import SettingCheckbox from "../SettingCheckbox";

interface WeaviateSectionProps {
  currentUserConfig: BackendConfig | null;
  currentFrontendConfig: FrontendConfig | null;
  weaviateIssues: string[];
  wcdUrlValid: boolean;
  wcdApiKeyValid: boolean;
  customWeaviateHttpHostValid: boolean;
  customWeaviateGrpcHostValid: boolean;
  onUpdateSettings: (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    keyOrUpdates: string | Record<string, any>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    value?: any
  ) => void;
  onUpdateFrontend: (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    keyOrUpdates: string | Record<string, any>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    value?: any
  ) => void;
}

/**
 * Component for configuring Weaviate cluster settings
 * Handles URL, API key, and timeout configurations
 */
export default function WeaviateSection({
  currentUserConfig,
  currentFrontendConfig,
  weaviateIssues,
  wcdUrlValid,
  wcdApiKeyValid,
  customWeaviateHttpHostValid,
  customWeaviateGrpcHostValid,
  onUpdateSettings,
  onUpdateFrontend,
}: WeaviateSectionProps) {
  const isLocal = currentUserConfig?.settings.WEAVIATE_IS_LOCAL as boolean;
  const isCustom = currentUserConfig?.settings.WEAVIATE_IS_CUSTOM as boolean;

  return (
    <SettingCard>
      <SettingHeader
        icon={<FaDatabase />}
        className="bg-accent"
        header="Cụm Weaviate"
        buttonIcon={<BsDatabaseFillAdd />}
        buttonText="Tạo cụm"
        onClick={() => {
          window.open("https://console.weaviate.cloud/", "_blank");
        }}
      />

      {/* Warning Card for Weaviate Issues */}
      {weaviateIssues.length > 0 && (
        <WarningCard
          title="Cần cấu hình Weaviate"
          issues={weaviateIssues}
        />
      )}

      <SettingGroup>
        <SettingItem>
          <SettingTitle
            title="Loại cụm"
            description="Chọn giữa cụm đám mây, cục bộ hoặc tùy chỉnh Weaviate."
          />
          <SettingToggle
            value={isLocal ? "Local" : isCustom ? "Custom" : "Cloud"}
            onChange={(value) => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const updates: Record<string, any> = {
                WEAVIATE_IS_LOCAL: value === "Local",
                WEAVIATE_IS_CUSTOM: value === "Custom",
              };

              // Auto-populate URL when switching to local if it's empty
              if (
                value === "Local" &&
                (!currentUserConfig?.settings?.WCD_URL ||
                  currentUserConfig.settings.WCD_URL.trim() === "")
              ) {
                updates.WCD_URL = "http://localhost";
              }

              onUpdateSettings(updates);
            }}
            labels={["Cloud", "Local", "Custom"]}
            icons={[
              <FaCloud key="cloud" />,
              <FaServer key="server" />,
              <FaDatabase key="custom" />,
            ]}
          />
        </SettingItem>
        {!isCustom && (
          <SettingItem>
            <SettingTitle
              title="URL"
              description="Địa chỉ URL của cụm Weaviate của bạn."
            />
            <SettingInput
              isProtected={false}
              value={currentUserConfig?.settings.WCD_URL || ""}
              onChange={(value) => {
                onUpdateSettings("WCD_URL", value);
              }}
              isInvalid={!wcdUrlValid}
            />
          </SettingItem>
        )}
        {isLocal && (
          <>
            <SettingItem>
              <SettingTitle
                title="Cổng GRPC"
                description="Cổng GRPC của cụm Weaviate cục bộ."
              />
              <SettingInput
                isProtected={false}
                value={
                  currentUserConfig?.settings.LOCAL_WEAVIATE_GRPC_PORT || 0
                }
                onChange={(value) => {
                  onUpdateSettings("LOCAL_WEAVIATE_GRPC_PORT", value);
                }}
                disabled={!isLocal}
              />
            </SettingItem>
            <SettingItem>
              <SettingTitle
                title="Cổng"
                description="Cổng của cụm Weaviate cục bộ."
              />
              <SettingInput
                isProtected={false}
                value={currentUserConfig?.settings.LOCAL_WEAVIATE_PORT || 0}
                onChange={(value) => {
                  onUpdateSettings("LOCAL_WEAVIATE_PORT", value);
                }}
                disabled={!isLocal}
              />
            </SettingItem>
          </>
        )}

        {isCustom && (
          <>
            <SettingItem>
              <SettingTitle
                title="Máy chủ HTTP"
                description="Máy chủ HTTP của Weaviate tùy chỉnh của bạn."
              />
              <SettingInput
                isProtected={false}
                value={
                  (currentUserConfig?.settings.CUSTOM_HTTP_HOST as string) || ""
                }
                onChange={(value) => {
                  onUpdateSettings("CUSTOM_HTTP_HOST", value);
                }}
                disabled={!isCustom}
                isInvalid={!customWeaviateHttpHostValid}
              />
            </SettingItem>
            <SettingItem>
              <SettingTitle
                title="Cổng HTTP"
                description="Cổng HTTP của Weaviate tùy chỉnh của bạn."
              />
              <SettingInput
                isProtected={false}
                value={
                  (currentUserConfig?.settings.CUSTOM_HTTP_PORT as number) || 80
                }
                onChange={(value) => {
                  onUpdateSettings("CUSTOM_HTTP_PORT", value);
                }}
                disabled={!isCustom}
              />
            </SettingItem>
            <SettingItem>
              <SettingTitle
                title="HTTP bảo mật"
                description="Kết nối HTTP có bảo mật hay không."
              />
              <SettingCheckbox
                value={
                  (currentUserConfig?.settings.CUSTOM_HTTP_SECURE as boolean) ||
                  false
                }
                onChange={(value) => {
                  onUpdateSettings("CUSTOM_HTTP_SECURE", value);
                }}
              />
            </SettingItem>
            <SettingItem>
              <SettingTitle
                title="Máy chủ GRPC"
                description="Máy chủ GRPC của Weaviate tùy chỉnh của bạn."
              />
              <SettingInput
                isProtected={false}
                value={
                  (currentUserConfig?.settings.CUSTOM_GRPC_HOST as string) || ""
                }
                onChange={(value) => {
                  onUpdateSettings("CUSTOM_GRPC_HOST", value);
                }}
                disabled={!isCustom}
                isInvalid={!customWeaviateGrpcHostValid}
              />
            </SettingItem>
            <SettingItem>
              <SettingTitle
                title="Cổng GRPC"
                description="Cổng GRPC của Weaviate tùy chỉnh của bạn."
              />
              <SettingInput
                isProtected={false}
                value={
                  (currentUserConfig?.settings.CUSTOM_GRPC_PORT as number) ||
                  50051
                }
                onChange={(value) => {
                  onUpdateSettings("CUSTOM_GRPC_PORT", value);
                }}
                disabled={!isCustom}
              />
            </SettingItem>
            <SettingItem>
              <SettingTitle
                title="GRPC bảo mật"
                description="Kết nối GRPC có bảo mật hay không."
              />
              <SettingCheckbox
                value={
                  (currentUserConfig?.settings.CUSTOM_GRPC_SECURE as boolean) ||
                  false
                }
                onChange={(value) => {
                  onUpdateSettings("CUSTOM_GRPC_SECURE", value);
                }}
              />
            </SettingItem>
          </>
        )}

        <SettingItem>
          <SettingTitle
            title="Khóa API"
            description={
              isLocal
                ? "Khóa API của cụm Weaviate cục bộ. Cần được cấu hình trong cụm Weaviate cục bộ."
                : isCustom
                  ? "Khóa API của Weaviate tùy chỉnh của bạn."
                  : "Khóa API của cụm Weaviate của bạn."
            }
          />
          <SettingInput
            isProtected={true}
            value={currentUserConfig?.settings.WCD_API_KEY || ""}
            onChange={(value) => {
              onUpdateSettings("WCD_API_KEY", value);
            }}
            isInvalid={!isLocal && !isCustom && !wcdApiKeyValid}
          />
        </SettingItem>

        <SettingItem>
          <SettingTitle
            title="Thời gian chờ cây"
            description="Thời gian chờ cho cây quyết định."
          />
          <SettingInput
            isProtected={false}
            value={currentFrontendConfig?.tree_timeout || 0}
            onChange={(value) => {
              onUpdateFrontend("tree_timeout", value);
            }}
          />
        </SettingItem>

        <SettingItem>
          <SettingTitle
            title="Thời gian chờ máy khách"
            description="Thời gian chờ cho máy khách."
          />
          <SettingInput
            isProtected={false}
            value={currentFrontendConfig?.client_timeout || 0}
            onChange={(value) => {
              onUpdateFrontend("client_timeout", value);
            }}
          />
        </SettingItem>
      </SettingGroup>
    </SettingCard>
  );
}
