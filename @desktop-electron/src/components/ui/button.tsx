import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:pointer-events-none disabled:opacity-45 active:scale-[0.985]",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-soft hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline: "border border-glass-border/35 bg-background/[0.35] text-foreground shadow-soft hover:border-glass-border/50 hover:bg-glass/80 hover:text-accent-foreground",
        secondary: "bg-secondary/80 text-secondary-foreground shadow-soft hover:bg-secondary",
        ghost: "text-muted-foreground hover:bg-glass/80 hover:text-foreground",
        subtle: "border border-glass-border/35 bg-card/70 text-muted-foreground shadow-soft hover:border-glass-border/50 hover:bg-glass/80 hover:text-foreground",
        command: "border border-glass-border/35 bg-card/80 text-foreground shadow-soft hover:border-glass-border/50 hover:bg-glass/80",
      },
      size: {
        default: "h-9 px-3.5",
        sm: "h-8 px-3 text-xs",
        xs: "h-7 px-2 text-xs",
        icon: "h-8 w-8",
        iconSm: "h-7 w-7",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
