import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "../../ui/dropdown-menu";

export function FilterSelect({
  label,
  icon,
  value,
  options,
  onChange,
}: {
  label: string;
  icon: ReactNode;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  const selectedLabel = options.find((option) => option.value === value)?.label ?? options[0]?.label ?? label;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`${label}: ${selectedLabel}`}
          className="group inline-flex h-9 min-w-[148px] max-w-[260px] items-center gap-2 rounded-xl border border-glass-border/25 bg-card/70 px-3 text-left text-xs text-muted-foreground shadow-soft transition-[background,border-color,box-shadow] duration-150 hover:border-glass-border/45 hover:bg-glass/80 hover:text-foreground data-[state=open]:border-primary/25 data-[state=open]:bg-accent/65 data-[state=open]:text-foreground"
        >
          <span className="shrink-0 text-primary/90">{icon}</span>
          <span className="min-w-0 flex-1 truncate font-medium text-foreground">{selectedLabel}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150 group-data-[state=open]:rotate-180" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="personagent-dropdown-fade w-[var(--radix-dropdown-menu-trigger-width)] min-w-48 rounded-xl p-1.5">
        <DropdownMenuLabel className="px-2 py-1 text-[10px]">{label}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={value} onValueChange={onChange}>
          {options.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value} className="min-w-0 gap-2 rounded-lg py-2 pr-2 text-[12px]">
              <span className="min-w-0 truncate">{option.label}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
