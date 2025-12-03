import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "px-2 py-1 flex flex-row justify-center items-center gap-1 rounded-full text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "text-primary bg-foreground_alt",
        accent: "text-accent bg-accent/15 border border-accent/30",
        warning: "text-warning bg-warning/15 border border-warning/30",
        success: "text-accent bg-accent/10",
        destructive: "text-error bg-error/15 border border-error/30",
        outline: "text-secondary border border-secondary/30",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
