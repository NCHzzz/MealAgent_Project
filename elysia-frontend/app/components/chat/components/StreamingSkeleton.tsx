"use client";

import { motion } from "framer-motion";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface StreamingSkeletonProps {
  lines?: number;
  variant?: "default" | "compact" | "expanded";
}

const StreamingSkeleton: React.FC<StreamingSkeletonProps> = ({ 
  lines = 4,
  variant = "default"
}) => {
  const lineWidths = [
    "w-full",
    "w-5/6",
    "w-4/5",
    "w-3/4",
    "w-2/3",
  ];

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1,
        delayChildren: 0.1,
      },
    },
  };

  const itemVariants = {
    hidden: { 
      opacity: 0, 
      x: -20,
      scale: 0.95
    },
    visible: { 
      opacity: 1, 
      x: 0,
      scale: 1,
      transition: {
        type: "spring" as const,
        damping: 20,
        stiffness: 300,
      }
    },
  };

  const shimmerVariants = {
    initial: {
      backgroundPosition: "-200% 0",
    },
    animate: {
      backgroundPosition: "200% 0",
      transition: {
        duration: 2,
        repeat: Infinity,
        ease: "linear",
      },
    },
  };

  return (
    <motion.div
      className="w-full flex flex-col gap-2 justify-start items-start fade-in"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      {/* Streaming indicator */}
      <motion.div
        className="flex items-center gap-2 mb-2"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <motion.div
          className="flex gap-1"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
        >
          {[0, 1, 2].map((i) => (
            <motion.div
              key={i}
              className="w-1.5 h-1.5 bg-accent rounded-full"
              animate={{
                y: [0, -4, 0],
                opacity: [0.5, 1, 0.5],
              }}
              transition={{
                duration: 0.8,
                repeat: Infinity,
                delay: i * 0.2,
                ease: "easeInOut",
              }}
            />
          ))}
        </motion.div>
        <motion.span
          className="text-xs text-secondary"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
        >
          Đang suy nghĩ...
        </motion.span>
      </motion.div>

      {/* Animated skeleton lines */}
      {Array.from({ length: lines }).map((_, index) => (
        <motion.div
          key={index}
          className="w-full"
          variants={itemVariants}
        >
          <Skeleton
            className={cn(
              "h-4 rounded-md",
              lineWidths[index % lineWidths.length],
              "bg-gradient-to-r from-background_alt via-accent/10 to-background_alt",
              "bg-[length:200%_100%]"
            )}
            style={{
              animation: "shimmer 2s infinite linear",
            }}
          />
        </motion.div>
      ))}

      <style jsx>{`
        @keyframes shimmer {
          0% {
            background-position: -200% 0;
          }
          100% {
            background-position: 200% 0;
          }
        }
      `}</style>
    </motion.div>
  );
};

export default StreamingSkeleton;

