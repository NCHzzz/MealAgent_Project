"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface StreamingIndicatorProps {
  isStreaming: boolean;
  message?: string;
  variant?: "default" | "compact" | "minimal";
  className?: string;
}

const StreamingIndicator: React.FC<StreamingIndicatorProps> = ({
  isStreaming,
  message = "Đang xử lý...",
  variant = "default",
  className,
}) => {
  if (!isStreaming) return null;

  return (
    <motion.div
      className={cn(
        "flex items-center gap-2 text-xs text-secondary",
        variant === "compact" && "gap-1.5",
        variant === "minimal" && "gap-1",
        className
      )}
      initial={{ opacity: 0, y: -5 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -5 }}
      transition={{ duration: 0.2 }}
    >
      {/* Animated dots */}
      <div className="flex gap-1 items-center">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className={cn(
              "bg-accent rounded-full",
              variant === "compact" ? "w-1 h-1" : variant === "minimal" ? "w-0.5 h-0.5" : "w-1.5 h-1.5"
            )}
            animate={{
              y: [0, -4, 0],
              opacity: [0.5, 1, 0.5],
              scale: [1, 1.2, 1],
            }}
            transition={{
              duration: 0.8,
              repeat: Infinity,
              delay: i * 0.2,
              ease: "easeInOut",
            }}
          />
        ))}
      </div>

      {/* Message text (hidden in minimal variant) */}
      {variant !== "minimal" && (
        <motion.span
          className="text-secondary/80"
          animate={{
            opacity: [0.6, 1, 0.6],
          }}
          transition={{
            duration: 1.5,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        >
          {message}
        </motion.span>
      )}
    </motion.div>
  );
};

export default StreamingIndicator;

