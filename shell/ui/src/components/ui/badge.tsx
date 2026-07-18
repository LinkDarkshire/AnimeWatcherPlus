import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", {
  variants: {
    variant: {
      default: "bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]",
      outline: "border border-[hsl(var(--border))] text-[hsl(var(--foreground))]",
      destructive: "bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))]",
    },
  },
  defaultVariants: { variant: "default" },
})

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
