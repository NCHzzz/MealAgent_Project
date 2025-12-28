"use client";

import React from "react";
import { MdStorage } from "react-icons/md";
import { IoCopy } from "react-icons/io5";
import { FaCloud, FaServer, FaDatabase } from "react-icons/fa";
import { Button } from "@/components/ui/button";
import {
  SettingCard,
  SettingGroup,
  SettingItem,
  SettingTitle,
  SettingToggle,
} from "../SettingComponents";
import SettingInput from "../SettingInput";
import SettingCheckbox from "../SettingCheckbox";
import WarningCard from "../WarningCard";
import { FrontendConfig } from "@/app/types/objects";

interface StorageSectionProps {
  currentFrontendConfig: FrontendConfig | null;
  storageIssues: string[];
  shouldHighlightUseSameCluster: boolean;
  customStorageHttpHostValid: boolean;
  customStorageGrpcHostValid: boolean;
  onUpdateFrontend: (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    keyOrUpdates: string | Record<string, any>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    value?: any
  ) => void;
  onCopyWeaviateValues: () => void;
}

/**
 * Component for configuring Elysia storage settings
 * Handles storage URL, API key, and save options for configs and conversations
 */
export default function StorageSection({
  currentFrontendConfig,
  storageIssues,
  shouldHighlightUseSameCluster,
  onUpdateFrontend,
  onCopyWeaviateValues,
  customStorageHttpHostValid,
  customStorageGrpcHostValid,
}: StorageSectionProps) {
  const isLocal = currentFrontendConfig?.save_location_weaviate_is_local;
  const isCustom = currentFrontendConfig?.save_location_weaviate_is_custom;

  return (
    <SettingCard>
      <div className="flex flex-col sm:flex-row items-start sm:items-center w-full justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 bg-background rounded-md flex items-center justify-center">
            <MdStorage />
          </div>
          <p className="text-primary text-lg">Lưu trữ Elysia</p>
        </div>
        <div className="flex items-center justify-end w-full sm:w-auto">
          <div>
            <Button
              variant="default"
              onClick={onCopyWeaviateValues}
              className={`flex items-center gap-2 w-full sm:w-[10rem] ${
                shouldHighlightUseSameCluster
                  ? "bg-highlight/10 text-highlight hover:bg-highlight/20 border-highlight/30"
                  : ""
              }`}
            >
              <IoCopy />
              <span className="text-sm font-base">Dùng cùng cụm</span>
            </Button>
          </div>
        </div>
      </div>

      {/* Warning Card for Storage Issues */}
      {storageIssues.length > 0 && (
        <WarningCard
          title="Cần cấu hình lưu trữ"
          issues={storageIssues}
        />
      )}

      <SettingGroup>
        <SettingItem>
          <SettingTitle
            title="Loại lưu trữ"
            description="Chọn giữa lưu trữ Weaviate cục bộ hoặc từ xa."
          />
          <SettingToggle
            value={isLocal ? "Local" : isCustom ? "Custom" : "Cloud"}
            onChange={(value) => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const updates: Record<string, any> = {
                save_location_weaviate_is_local: value === "Local",
                save_location_weaviate_is_custom: value === "Custom",
              };

              // Auto-populate URL when switching to local if it's empty
              if (
                value === "Local" &&
                (!currentFrontendConfig?.save_location_wcd_url ||
                  currentFrontendConfig.save_location_wcd_url.trim() === "")
              ) {
                updates.save_location_wcd_url = "http://localhost";
              }
              onUpdateFrontend(updates);
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
              description="Địa chỉ URL của cụm Weaviate để lưu cấu hình và cuộc trò chuyện."
            />
            <SettingInput
              key="elysia-storage-url"
              isProtected={false}
              value={currentFrontendConfig?.save_location_wcd_url || ""}
              onChange={(value) => {
                onUpdateFrontend("save_location_wcd_url", value);
              }}
              isInvalid={
                (currentFrontendConfig?.save_configs_to_weaviate ||
                  currentFrontendConfig?.save_trees_to_weaviate) &&
                !currentFrontendConfig?.save_location_wcd_url?.trim()
              }
            />
          </SettingItem>
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
                  currentFrontendConfig?.save_location_custom_http_host || ""
                }
                onChange={(value) => {
                  onUpdateFrontend("save_location_custom_http_host", value);
                }}
                isInvalid={!customStorageHttpHostValid}
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
                  currentFrontendConfig?.save_location_custom_http_port || 80
                }
                onChange={(value) => {
                  onUpdateFrontend("save_location_custom_http_port", value);
                }}
              />
            </SettingItem>
            <SettingItem>
              <SettingTitle
                title="HTTP bảo mật"
                description="Kết nối HTTP có bảo mật hay không."
              />
              <SettingCheckbox
                value={
                  currentFrontendConfig?.save_location_custom_http_secure ||
                  false
                }
                onChange={(value) => {
                  onUpdateFrontend("save_location_custom_http_secure", value);
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
                  currentFrontendConfig?.save_location_custom_grpc_host || ""
                }
                onChange={(value) => {
                  onUpdateFrontend("save_location_custom_grpc_host", value);
                }}
                isInvalid={!customStorageGrpcHostValid}
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
                  currentFrontendConfig?.save_location_custom_grpc_port || 50051
                }
                onChange={(value) => {
                  onUpdateFrontend("save_location_custom_grpc_port", value);
                }}
              />
            </SettingItem>
            <SettingItem>
              <SettingTitle
                title="GRPC bảo mật"
                description="Kết nối GRPC có bảo mật hay không."
              />
              <SettingCheckbox
                value={
                  currentFrontendConfig?.save_location_custom_grpc_secure ||
                  false
                }
                onChange={(value) => {
                  onUpdateFrontend("save_location_custom_grpc_secure", value);
                }}
              />
            </SettingItem>
          </>
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
                  currentFrontendConfig?.save_location_local_weaviate_grpc_port ||
                  50051
                }
                onChange={(value) => {
                  onUpdateFrontend("save_location_weaviate_grpc_port", value);
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
                value={
                  currentFrontendConfig?.save_location_local_weaviate_port || 0
                }
                onChange={(value) => {
                  onUpdateFrontend("save_location_weaviate_port", value);
                }}
                disabled={!isLocal}
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
                : "Khóa API của cụm Weaviate để lưu cấu hình và cuộc trò chuyện."
            }
          />
          <SettingInput
            key="elysia-storage-api-key"
            isProtected={true}
            value={currentFrontendConfig?.save_location_wcd_api_key || ""}
            onChange={(value) => {
              onUpdateFrontend("save_location_wcd_api_key", value);
            }}
            isInvalid={
              !isLocal &&
              !isCustom &&
              (currentFrontendConfig?.save_configs_to_weaviate ||
                currentFrontendConfig?.save_trees_to_weaviate) &&
              !currentFrontendConfig?.save_location_wcd_api_key?.trim()
            }
          />
        </SettingItem>

        <SettingItem>
          <SettingTitle
            title="Lưu cuộc trò chuyện"
            description="Lưu cuộc trò chuyện vào Weaviate."
          />
          <SettingCheckbox
            value={currentFrontendConfig?.save_trees_to_weaviate || false}
            onChange={(value) => {
              onUpdateFrontend("save_trees_to_weaviate", value);
            }}
          />
        </SettingItem>

        <SettingItem>
          <SettingTitle
            title="Lưu cấu hình"
            description="Lưu cấu hình vào Weaviate."
          />
          <SettingCheckbox
            value={currentFrontendConfig?.save_configs_to_weaviate || false}
            onChange={(value) => {
              onUpdateFrontend("save_configs_to_weaviate", value);
            }}
          />
        </SettingItem>
      </SettingGroup>
    </SettingCard>
  );
}
