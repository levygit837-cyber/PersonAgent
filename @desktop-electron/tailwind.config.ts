import typography from "@tailwindcss/typography";
import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "Geist", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: "hsl(var(--card))",
        "card-foreground": "hsl(var(--card-foreground))",
        popover: "hsl(var(--popover))",
        "popover-foreground": "hsl(var(--popover-foreground))",
        primary: "hsl(var(--primary))",
        "primary-foreground": "hsl(var(--primary-foreground))",
        secondary: "hsl(var(--secondary))",
        "secondary-foreground": "hsl(var(--secondary-foreground))",
        muted: "hsl(var(--muted))",
        "muted-foreground": "hsl(var(--muted-foreground))",
        accent: "hsl(var(--accent))",
        "accent-foreground": "hsl(var(--accent-foreground))",
        glass: "hsl(var(--glass))",
        "glass-border": "hsl(var(--glass-border))",
        destructive: "hsl(var(--destructive))",
        "destructive-foreground": "hsl(var(--destructive-foreground))",
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        success: "hsl(var(--success))",
        warning: "hsl(var(--warning))",
      },
      borderRadius: {
        DEFAULT: "calc(var(--radius) - 8px)",
        sm: "calc(var(--radius) - 6px)",
        md: "calc(var(--radius) - 4px)",
        lg: "var(--radius)",
        xl: "calc(var(--radius) + 2px)",
        "2xl": "calc(var(--radius) + 8px)",
      },
      boxShadow: {
        dock: "0 26px 70px rgb(0 0 0 / 0.56), 0 0 0 1px rgb(237 141 78 / 0.018), inset 0 1px 0 rgb(255 236 214 / 0.026)",
        soft: "0 10px 28px rgb(0 0 0 / 0.24), inset 0 1px 0 rgb(255 236 214 / 0.014)",
        floating: "0 22px 54px rgb(0 0 0 / 0.48), 0 0 0 1px rgb(237 141 78 / 0.022), inset 0 1px 0 rgb(255 236 214 / 0.028)",
      },
    },
  },
  plugins: [typography],
} satisfies Config;
