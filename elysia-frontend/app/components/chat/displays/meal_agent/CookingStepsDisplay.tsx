"use client";

import React, { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { CookingStepsPayload } from "@/app/types/displays";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FaPlay, FaPause, FaRedo } from "react-icons/fa";
import DisplayPagination from "../../components/DisplayPagination";

interface CookingStepsDisplayProps {
  steps: CookingStepsPayload[];
  handleResultPayloadChange?: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => void;
}

const CookingStepsDisplay: React.FC<CookingStepsDisplayProps> = ({
  steps,
  handleResultPayloadChange,
}) => {
  if (steps.length === 0) return null;

  return (
    <DisplayPagination>
      {steps.map((stepData, idx) => (
        <CookingStepsCard
          key={`${stepData.food_id}-${idx}`}
          stepData={stepData}
          index={idx}
        />
      ))}
    </DisplayPagination>
  );
};

interface CookingStepsCardProps {
  stepData: CookingStepsPayload;
  index: number;
}

const CookingStepsCard: React.FC<CookingStepsCardProps> = ({
  stepData,
  index,
}) => {
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [timeRemaining, setTimeRemaining] = useState<number | null>(null);

  const totalTime = stepData.steps.reduce(
    (sum, step) => sum + step.estimated_seconds,
    0
  );

  useEffect(() => {
    if (!isPlaying || timeRemaining === null || timeRemaining <= 0) {
      if (timeRemaining === 0 && currentStep < stepData.steps.length - 1) {
        setCurrentStep((prev) => prev + 1);
        setTimeRemaining(stepData.steps[currentStep + 1]?.estimated_seconds || 0);
      }
      return;
    }

    const timer = setInterval(() => {
      setTimeRemaining((prev) => {
        if (prev === null || prev <= 0) return 0;
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [isPlaying, timeRemaining, currentStep, stepData.steps]);

  const handlePlay = () => {
    if (timeRemaining === null) {
      setTimeRemaining(stepData.steps[currentStep]?.estimated_seconds || 0);
    }
    setIsPlaying(true);
  };

  const handlePause = () => {
    setIsPlaying(false);
  };

  const handleReset = () => {
    setCurrentStep(0);
    setIsPlaying(false);
    setTimeRemaining(stepData.steps[0]?.estimated_seconds || null);
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.1 }}
    >
      <Card className="w-full bg-background_alt border-secondary/10">
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle className="text-lg">{stepData.dish_name}</CardTitle>
            <Badge variant="outline" className="text-xs">
              {stepData.steps.length} steps
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Timer Controls */}
          <div className="flex items-center gap-2 p-3 bg-background rounded-lg">
            <div className="flex-1">
              <p className="text-xs text-secondary mb-1">Current Step Timer</p>
              <p className="text-2xl font-mono font-semibold text-primary">
                {timeRemaining !== null ? formatTime(timeRemaining) : "--:--"}
              </p>
            </div>
            <div className="flex gap-2">
              {!isPlaying ? (
                <Button
                  size="sm"
                  onClick={handlePlay}
                  className="flex items-center gap-1"
                >
                  <FaPlay className="w-4 h-4" />
                  Play
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handlePause}
                  className="flex items-center gap-1"
                >
                  <FaPause className="w-4 h-4" />
                  Pause
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={handleReset}
                className="flex items-center gap-1"
              >
                <FaRedo className="w-4 h-4" />
                Reset
              </Button>
            </div>
          </div>

          {/* Steps */}
          <div className="space-y-2">
            {stepData.steps.map((step, stepIdx) => (
              <motion.div
                key={stepIdx}
                initial={{ opacity: 0, x: -20 }}
                animate={{
                  opacity: 1,
                  x: 0,
                  backgroundColor:
                    stepIdx === currentStep
                      ? "rgba(var(--primary), 0.1)"
                      : "transparent",
                }}
                transition={{ delay: stepIdx * 0.05 }}
                className={`p-3 rounded-lg border transition-all ${
                  stepIdx === currentStep
                    ? "border-primary/30 bg-primary/5"
                    : "border-secondary/5"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-sm font-semibold text-primary">
                    {step.index}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-primary">{step.instruction}</p>
                    {step.estimated_seconds > 0 && (
                      <p className="text-xs text-secondary mt-1">
                        Est. {formatTime(step.estimated_seconds)}
                      </p>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Total Time */}
          {totalTime > 0 && (
            <div className="pt-3 border-t border-secondary/10">
              <p className="text-xs text-secondary">
                Total estimated time: {formatTime(totalTime)}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default CookingStepsDisplay;

