"use client";

import React from "react";
import { TbManualGearboxFilled, TbArrowBackUp } from "react-icons/tb";
import { DeleteButton } from "@/app/components/navigation/DeleteButton";
import { FaRobot } from "react-icons/fa";
import { IoInformationCircle } from "react-icons/io5";
import {
  SettingCard,
  SettingHeader,
  SettingGroup,
  SettingItem,
  SettingTitle,
} from "../SettingComponents";
import SettingCombobox from "../SettingCombobox";
import SettingInput from "../SettingInput";
import WarningCard from "../WarningCard";
import ModelBadges from "../ModelBadge";
import { BackendConfig, ModelProvider } from "@/app/types/objects";

interface ModelsSectionProps {
  currentUserConfig: BackendConfig | null;
  modelsData: { [key: string]: ModelProvider } | null;
  loadingModels: boolean;
  modelsIssues: string[];
  baseProviderValid?: boolean;
  baseModelValid?: boolean;
  complexProviderValid?: boolean;
  complexModelValid?: boolean;
  onUpdateSettings: (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    keyOrUpdates: string | Record<string, any>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    value?: any
  ) => void;
  onUpdateConfig: (config: BackendConfig) => void;
  setChangedConfig: (changed: boolean) => void;
  showDocumentation?: boolean; // Option to show/hide "Available Models" button
  title?: string; // Optional title override
  onResetConfig?: () => void; // Optional reset function for tree settings
}

/**
 * Component for configuring AI models settings
 * Handles base and complex model selection, provider settings, and API base URL
 */
export default function ModelsSection({
  currentUserConfig,
  modelsData,
  loadingModels,
  modelsIssues,
  baseProviderValid = true,
  baseModelValid = true,
  complexProviderValid = true,
  complexModelValid = true,
  onUpdateSettings,
  onUpdateConfig,
  setChangedConfig,
  showDocumentation = true,
  title = "Models",
  onResetConfig,
}: ModelsSectionProps) {
  return (
    <SettingCard>
      <SettingHeader
        icon={<TbManualGearboxFilled />}
        className="bg-alt_color_a"
        header={title}
        buttonIcon={showDocumentation ? <FaRobot /> : undefined}
        buttonText={showDocumentation ? "Mô hình có sẵn" : undefined}
        onClick={
          showDocumentation
            ? () => {
                window.open("https://openrouter.ai/models", "_blank");
              }
            : undefined
        }
      />

      {/* Warning Card for Models Issues */}
      {modelsIssues.length > 0 && (
        <WarningCard
          title="Cần cấu hình mô hình"
          issues={modelsIssues}
        />
      )}

      <SettingGroup>
        {/* Base Model Configuration */}
        <div className="flex flex-col gap-3">
          <div className="flex flex-col w-full">
            <div className="flex items-center justify-start gap-2">
              <p className="text-primary font-bold">Mô hình cơ bản</p>
            </div>
            <p className="text-sm text-secondary">
              Được sử dụng cho agent quyết định, cũng như bất kỳ công cụ nào yêu cầu
              tác vụ đơn giản cần tốc độ hơn độ chính xác. Có thể giống với
              mô hình phức tạp để đảm bảo tính nhất quán nhưng giảm hiệu suất.
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:gap-4 w-full">
            <div className="w-full">
              <p className="text-sm text-secondary mb-2">Nhà cung cấp</p>
              <SettingCombobox
                value={currentUserConfig?.settings.BASE_PROVIDER || ""}
                values={modelsData ? Object.keys(modelsData) : []}
                onChange={(value) => {
                  // Update both provider and clear model in a single state update
                  if (currentUserConfig) {
                    onUpdateConfig({
                      ...currentUserConfig,
                      settings: {
                        ...currentUserConfig.settings,
                        BASE_PROVIDER: value,
                        BASE_MODEL: "", // Clear base model when provider changes
                      },
                    });
                    setChangedConfig(true);
                  }
                }}
                placeholder={
                  loadingModels ? "Đang tải nhà cung cấp..." : "Chọn nhà cung cấp..."
                }
                searchPlaceholder="Tìm nhà cung cấp..."
                isInvalid={!baseProviderValid}
              />
            </div>
            {currentUserConfig?.settings.BASE_PROVIDER && (
              <div className="w-full">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-2">
                  <p className="text-sm text-secondary">Mô hình</p>
                  <ModelBadges
                    modelsData={modelsData}
                    provider={currentUserConfig?.settings.BASE_PROVIDER || ""}
                    model={currentUserConfig?.settings.BASE_MODEL || ""}
                  />
                </div>
                <SettingCombobox
                  value={currentUserConfig?.settings.BASE_MODEL || ""}
                  values={
                    modelsData && currentUserConfig?.settings.BASE_PROVIDER
                      ? Object.keys(
                          modelsData[
                            currentUserConfig.settings.BASE_PROVIDER
                          ] || {}
                        )
                      : []
                  }
                  onChange={(value) => {
                    onUpdateSettings("BASE_MODEL", value);
                  }}
                  placeholder={
                    loadingModels ? "Đang tải mô hình..." : "Chọn mô hình..."
                  }
                  searchPlaceholder="Tìm mô hình..."
                  isInvalid={!baseModelValid}
                />
              </div>
            )}
          </div>
        </div>

        {/* Complex Model Configuration */}
        <div className="flex flex-col gap-3">
          <div className="flex flex-col w-full">
            <div className="flex items-center justify-start gap-2">
              <p className="text-primary font-bold">Mô hình phức tạp</p>
            </div>
            <p className="text-sm text-secondary">
              Được sử dụng trong các công cụ yêu cầu tác vụ phức tạp cần độ chính xác
              và suy luận cao, như công cụ truy vấn và tổng hợp.
              Tốc độ có thể chậm hơn nhưng chất lượng cao hơn. Có thể giống với
              mô hình cơ bản.
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:gap-4 w-full">
            <div className="w-full">
              <p className="text-sm text-secondary mb-2">Nhà cung cấp</p>
              <SettingCombobox
                value={currentUserConfig?.settings.COMPLEX_PROVIDER || ""}
                values={modelsData ? Object.keys(modelsData) : []}
                onChange={(value) => {
                  // Update both provider and clear model in a single state update
                  if (currentUserConfig) {
                    onUpdateConfig({
                      ...currentUserConfig,
                      settings: {
                        ...currentUserConfig.settings,
                        COMPLEX_PROVIDER: value,
                        COMPLEX_MODEL: "", // Clear complex model when provider changes
                      },
                    });
                    setChangedConfig(true);
                  }
                }}
                placeholder={
                  loadingModels ? "Đang tải nhà cung cấp..." : "Chọn nhà cung cấp..."
                }
                searchPlaceholder="Tìm nhà cung cấp..."
                isInvalid={!complexProviderValid}
              />
            </div>
            {currentUserConfig?.settings.COMPLEX_PROVIDER && (
              <div className="w-full">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-2">
                  <p className="text-sm text-secondary">Mô hình</p>
                  <ModelBadges
                    modelsData={modelsData}
                    provider={
                      currentUserConfig?.settings.COMPLEX_PROVIDER || ""
                    }
                    model={currentUserConfig?.settings.COMPLEX_MODEL || ""}
                  />
                </div>
                <SettingCombobox
                  value={currentUserConfig?.settings.COMPLEX_MODEL || ""}
                  values={
                    modelsData && currentUserConfig?.settings.COMPLEX_PROVIDER
                      ? Object.keys(
                          modelsData[
                            currentUserConfig.settings.COMPLEX_PROVIDER
                          ] || {}
                        )
                      : []
                  }
                  onChange={(value) => {
                    onUpdateSettings("COMPLEX_MODEL", value);
                  }}
                  placeholder={
                    loadingModels ? "Đang tải mô hình..." : "Chọn mô hình..."
                  }
                  searchPlaceholder="Tìm mô hình..."
                  isInvalid={!complexModelValid}
                />
              </div>
            )}
          </div>
        </div>

        <SettingItem>
          <SettingTitle
            title="URL cơ sở API"
            description="Sử dụng để chỉ định điểm cuối tùy chỉnh để truy cập mô hình, như mô hình tự lưu trữ hoặc riêng tư"
          />
          <SettingInput
            isProtected={false}
            value={currentUserConfig?.settings.MODEL_API_BASE || ""}
            onChange={(value) => {
              onUpdateSettings("MODEL_API_BASE", value);
            }}
          />
        </SettingItem>

        {/* Model Usage Disclaimer */}
        <div className="flex flex-col gap-2 bg-highlight/10 rounded-lg p-3 text-sm text-highlight">
          <div className="flex flex-row gap-1 items-center">
            <IoInformationCircle className="text-highlight" />
            <p className="font-bold text-highlight">Lưu ý</p>
          </div>
          <p>
            Bạn có thể sử dụng cùng một mô hình cho cả tác vụ cơ bản và phức tạp. Sử dụng
            các mô hình khác nhau cho phép bạn cân bằng tốc độ và chất lượng - mô hình nhanh hơn
            cho tác vụ đơn giản và mô hình mạnh hơn cho suy luận phức tạp.
          </p>
        </div>

        <div className="flex flex-col gap-2 bg-alt_color_b/10 rounded-lg p-3 text-sm text-alt_color_b">
          <div className="flex flex-row gap-1 items-center">
            <IoInformationCircle className="text-alt_color_b" />
            <p className="font-bold text-alt_color_b">Đề xuất</p>
          </div>
          <p>
            Elysia được tối ưu hóa cho mô hình Gemini. Chúng tôi khuyên dùng mô hình Gemini
            thay vì mô hình OpenAI để có hiệu suất tốt nhất nếu có thể.
          </p>
        </div>

        {/* Reset config button for tree settings */}
        {onResetConfig && (
          <div className="flex w-full items-center justify-center pt-4">
            <DeleteButton
              onClick={onResetConfig}
              text="Đặt lại cấu hình"
              icon={<TbArrowBackUp />}
              confirmText="Bạn có chắc không?"
            />
          </div>
        )}
      </SettingGroup>
    </SettingCard>
  );
}
