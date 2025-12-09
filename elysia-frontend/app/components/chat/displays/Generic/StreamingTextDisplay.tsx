"use client";

import { TextPayload } from "@/app/types/chat";
import MarkdownFormat from "../../components/MarkdownFormat";
import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

interface StreamingTextDisplayProps {
  payload: TextPayload[];
  isStreaming?: boolean;
}

// Animation variants for smooth expand/collapse
const expandVariants = {
  collapsed: {
    height: 0,
    opacity: 0,
    transition: {
      height: {
        duration: 0.3,
        ease: "easeInOut" as const,
      },
      opacity: {
        duration: 0.2,
        delay: 0,
      },
    },
  },
  expanded: {
    height: "auto" as const,
    opacity: 1,
    transition: {
      height: {
        duration: 0.3,
        ease: "easeInOut" as const,
      },
      opacity: {
        duration: 0.3,
        delay: 0.1,
      },
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: -10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      type: "spring" as const,
      damping: 20,
      stiffness: 300,
    },
  },
  exit: {
    opacity: 0,
    y: -10,
    transition: {
      duration: 0.2,
    },
  },
};

// Streaming cursor component
const StreamingCursor = ({ isVisible }: { isVisible: boolean }) => (
  <motion.span
    className="inline-block w-0.5 h-4 bg-accent ml-1"
    animate={{
      opacity: isVisible ? [1, 1, 0, 0] : 0,
    }}
    transition={{
      duration: 1,
      repeat: Infinity,
      ease: "easeInOut",
    }}
  />
);

// Typewriter effect hook
const useTypewriter = (text: string, speed: number = 30, isStreaming: boolean = false) => {
  const [displayedText, setDisplayedText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!text) {
      setDisplayedText("");
      setIsTyping(false);
      return;
    }

    // If streaming, show text immediately but with smooth updates
    if (isStreaming) {
      setDisplayedText(text);
      setIsTyping(true);
      return;
    }

    // If not streaming, use typewriter effect for new content
    const currentLength = displayedText.length;
    if (text.length > currentLength) {
      setIsTyping(true);
      const newText = text.slice(0, currentLength + 1);
      setDisplayedText(newText);

      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }

      timeoutRef.current = setTimeout(() => {
        if (newText.length < text.length) {
          // Continue typing
          setDisplayedText(text.slice(0, newText.length + 1));
        } else {
          setIsTyping(false);
        }
      }, speed);
    } else if (text.length < currentLength) {
      // Text was updated/changed, reset
      setDisplayedText(text);
      setIsTyping(false);
    } else {
      setIsTyping(false);
    }

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [text, isStreaming]);

  return { displayedText, isTyping };
};

const StreamingTextDisplay: React.FC<StreamingTextDisplayProps> = ({
  payload,
  isStreaming = false,
}) => {
  // Non-streaming (history or finished): show all lines, no collapse, no cursor
  if (!isStreaming) {
    return (
      <div className="w-full flex flex-col gap-2 text-sm text-primary whitespace-pre-line leading-relaxed">
        {payload.map((item, idx) => (
          <p key={`${item.text}-${idx}`}>{item.text}</p>
        ))}
      </div>
    );
  }

  const [collapsed, setCollapsed] = useState(true);
  const latestText = payload.length > 0 ? payload[payload.length - 1].text : "";
  const previousTextRef = useRef("");

  // Detect if text is actually streaming (growing)
  const isActuallyStreaming =
    isStreaming && latestText.length > previousTextRef.current.length;

  useEffect(() => {
    previousTextRef.current = latestText;
  }, [latestText]);

  // For streaming: show latest text with typewriter-like smoothness
  const displayedText = latestText;
  const isTyping = false;

  const triggerCollapse = () => {
    setCollapsed((prev) => !prev);
  };

  return (
    <motion.div
      className="w-full flex flex-col items-start justify-start gap-3"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 20, stiffness: 300 }}
    >
      {/* Animated expandable section for older items */}
      {payload.length > 1 && (
        <motion.div
          variants={expandVariants}
          initial="collapsed"
          animate={!collapsed ? "expanded" : "collapsed"}
          className="overflow-hidden w-full"
        >
          <motion.div className="flex flex-col gap-2">
            <AnimatePresence>
              {!collapsed &&
                payload.slice(0, -1).map((item, index) => (
                  <motion.div
                    key={`${item.text}-${index}`}
                    className="flex gap-2 items-center justify-center"
                    variants={itemVariants}
                    initial="hidden"
                    animate="visible"
                    exit="exit"
                    transition={{ delay: index * 0.05 }}
                  >
                    <motion.p
                      className="text-xs w-5 h-5 bg-background_alt text-secondary p-2 rounded-full items-center justify-center flex flex-shrink-0"
                      initial={{ scale: 0, rotate: -180 }}
                      animate={{ scale: 1, rotate: 0 }}
                      transition={{
                        type: "spring",
                        damping: 15,
                        stiffness: 300,
                        delay: index * 0.05,
                      }}
                    >
                      {index + 1}
                    </motion.p>
                    <motion.div className="flex-1 min-w-0">
                      <MarkdownFormat text={item.text} variant="secondary" />
                    </motion.div>
                  </motion.div>
                ))}
            </AnimatePresence>
          </motion.div>
        </motion.div>
      )}

      {/* Latest item - always visible with streaming effect */}
      {payload.length > 0 && (
        <motion.div
          className="flex w-full gap-2 items-start cursor-pointer group"
          key={payload[payload.length - 1].text}
          onClick={triggerCollapse}
          whileHover={{ x: 2 }}
          whileTap={{ scale: 0.98 }}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            type: "spring",
            damping: 20,
            stiffness: 300,
            delay: 0.1,
          }}
        >
          {payload.length > 1 && (
            <motion.p
              className="text-xs bg-background_alt text-secondary p-2 w-5 h-5 rounded-full items-center justify-center flex flex-shrink-0 mt-1"
              whileHover={{ scale: 1.1 }}
              transition={{ type: "spring", damping: 15, stiffness: 400 }}
            >
              {payload.length}
            </motion.p>
          )}
          
          {/* Streaming indicator */}
          {isActuallyStreaming && (
            <motion.div
              className="flex-shrink-0 mt-1"
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0 }}
            >
              <motion.div
                className="w-2 h-2 bg-accent rounded-full"
                animate={{
                  scale: [1, 1.2, 1],
                  opacity: [0.7, 1, 0.7],
                }}
                transition={{
                  duration: 1.5,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
              />
            </motion.div>
          )}
          
          <motion.div 
            className={cn(
              "flex-1 min-w-0 transition-all duration-300",
              isActuallyStreaming && "opacity-90"
            )}
          >
            <div className="relative">
              <MarkdownFormat text={displayedText} />
              {(isTyping || isActuallyStreaming) && (
                <StreamingCursor isVisible={true} />
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </motion.div>
  );
};

export default StreamingTextDisplay;

