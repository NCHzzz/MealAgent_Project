"use client";

import React, { useContext, useEffect, useRef, useState } from "react";
import { FeedbackMetadata } from "../components/types";
import { Button } from "../../components/ui/button";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import { ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { MdOutlineFeedback } from "react-icons/md";

import { SessionContext } from "../components/contexts/SessionContext";
import { ChartConfig, ChartContainer } from "@/components/ui/chart";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getFeedback } from "../api/getFeedback";
import { RouterContext } from "../components/contexts/RouterContext";

const chartConfig = {
  count: {
    label: "Count",
    color: "#ffffff",
  },
} satisfies ChartConfig;

type ChartData = {
  day: string;
  count: number;
  positive: number;
  negative: number;
  very_positive: number;
};

export default function Home() {
  const { id } = useContext(SessionContext);
  const loading = useRef(false);
  const [feedbackMetadata, setFeedbackMetadata] =
    useState<FeedbackMetadata | null>(null);

  const { changePage } = useContext(RouterContext);

  const [feedbackChartData, setFeedbackChartData] = useState<ChartData[]>([]);

  const convertToChartData = (metadata: FeedbackMetadata) => {
    if (!metadata) return;

    // Create a map to group data by date
    const groupedData = new Map<string, ChartData>();

    for (const timestamp in metadata.feedback_by_date) {
      const date = new Date(timestamp);
      const displayDate = date.toLocaleDateString();
      // Use ISO date string for consistent sorting
      const sortableDate = date.toISOString().split("T")[0];

      if (!groupedData.has(sortableDate)) {
        groupedData.set(sortableDate, {
          day: displayDate, // Use formatted date for display
          count: 0,
          positive: 0,
          negative: 0,
          very_positive: 0,
        });
      }

      const existing = groupedData.get(sortableDate)!;
      const data = metadata.feedback_by_date[timestamp];
      groupedData.set(sortableDate, {
        ...existing,
        count: existing.count + data.count,
        positive: existing.positive + data.positive,
        negative: existing.negative + data.negative,
        very_positive: existing.very_positive + data.superpositive,
      });
    }

    // Convert map to array and sort by the sortable date string
    const chartData = Array.from(groupedData.values()).sort((a, b) => {
      const dateA = new Date(
        Object.keys(metadata.feedback_by_date).find(
          (timestamp) => new Date(timestamp).toLocaleDateString() === a.day
        ) || ""
      );
      const dateB = new Date(
        Object.keys(metadata.feedback_by_date).find(
          (timestamp) => new Date(timestamp).toLocaleDateString() === b.day
        ) || ""
      );
      return dateA.getTime() - dateB.getTime();
    });

    setFeedbackChartData(chartData);
  };

  const fetchMetadata = async () => {
    if (!id || loading.current) {
      return;
    }
    loading.current = true;
    const data = await getFeedback(id);
    setFeedbackMetadata(data);
    convertToChartData(data);
    loading.current = false;
  };

  const handleBrowseFeedback = () => {
    changePage("eval", { page: "feedback" }, true);
  };

  useEffect(() => {
    fetchMetadata();
  }, [id]);

  return (
    <div
      className="flex flex-col w-full gap-2 items-start justify-start"
      tabIndex={0}
    >
      <div className="flex flex-col gap-8 items-start justify-start w-full">
        <div className="flex-1">
          <h1 className="text-3xl md:text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-accent mb-2">Bảng điều khiển đánh giá</h1>
        </div>
        {loading.current && (
          <div className="w-full flex flex-col items-start justify-start gap-2 fade-in">
            <Skeleton className="w-full h-[25vh]" />
          </div>
        )}
        {!loading.current && feedbackMetadata && (
          <div className="w-full flex flex-col items-start justify-start gap-2 fade-in">
            <Card className="w-full">
              <CardHeader>
                <CardTitle>
                  <div className="w-full flex items-start justify-between">
                    <p>Đánh giá phản hồi</p>
                    <Button
                      onClick={handleBrowseFeedback}
                      className="text-primary"
                    >
                      <MdOutlineFeedback />
                      Duyệt phản hồi
                    </Button>
                  </div>
                </CardTitle>
                <CardDescription>
                  Phản hồi nhận được trong 30 ngày qua
                </CardDescription>
              </CardHeader>
              <CardContent className="flex lg:flex-row flex-col gap-2">
                <ChartContainer
                  config={chartConfig}
                  className="max-h-[25vh] lg:w-2/3 w-full"
                >
                  <BarChart accessibilityLayer data={feedbackChartData}>
                    <CartesianGrid vertical={false} />
                    <XAxis
                      dataKey="day"
                      tickLine={false}
                      tickMargin={10}
                      axisLine={false}
                      tickFormatter={(value) => value}
                    />
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Bar dataKey="positive" fill="#A5FF90" radius={3} />
                    <Bar dataKey="negative" fill="#BA2B2B" radius={3} />
                    <Bar dataKey="very_positive" fill="#ABCDFF" radius={3} />
                  </BarChart>
                </ChartContainer>
                <div className="w-full lg:w-1/3 flex flex-col border border-secondary rounded-md h-full">
                  <div className="flex flex-col flex-1 items-start justify-start gap-2 p-4 w-full border-b border-secondary">
                    <p className="text-secondary text-sm">Tổng phản hồi</p>
                    <p className="text-primary text-3xl font-bold">
                      {feedbackMetadata.total_feedback}
                    </p>
                  </div>
                  <div className="flex items-start justify-start w-full flex-1">
                    <div className="flex flex-col items-start justify-start border-r border-secondary gap-2 w-1/3 p-2">
                      <p className="text-secondary text-sm">Rất tích cực</p>
                      <p className="text-highlight text-3xl font-bold">
                        {feedbackMetadata.feedback_by_value.superpositive}
                      </p>
                    </div>
                    <div className="flex flex-col items-start justify-start border-r border-secondary gap-2 w-1/3 p-2">
                      <p className="text-secondary text-sm">Tích cực</p>
                      <p className="text-accent text-3xl font-bold">
                        {feedbackMetadata.feedback_by_value.positive}
                      </p>
                    </div>
                    <div className="flex flex-col items-start justify-start gap-2 w-1/3 p-2">
                      <p className="text-secondary text-sm">Tiêu cực</p>
                      <p className="text-error text-3xl font-bold">
                        {feedbackMetadata.feedback_by_value.negative}
                      </p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
