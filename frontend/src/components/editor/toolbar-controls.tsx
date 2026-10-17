"use client";

import { Ban } from "lucide-react";
import { forwardRef, useState, type ComponentProps, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

function modKey(): string {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)
    ? "⌘"
    : "Ctrl+";
}

/** "Mod-Shift-7" style shortcut label, e.g. "Ctrl+Shift+7". */
export function shortcut(keys: string): string {
  return keys.replace("Mod+", modKey());
}

interface ToolButtonProps extends Omit<ComponentProps<typeof Button>, "children" | "title"> {
  label: string;
  keys?: string;
  active?: boolean;
  children: ReactNode;
}

/** An icon button with an accessible name, a shortcut tooltip and an on/off (pressed) state. */
export const ToolButton = forwardRef<HTMLButtonElement, ToolButtonProps>(function ToolButton(
  { label, keys, active, className, children, onClick, ...props },
  ref,
) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            ref={ref}
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            aria-pressed={active === undefined ? undefined : active}
            data-active={active ? "true" : undefined}
            className={cn(
              "text-foreground/80 hover:text-foreground data-[active=true]:bg-primary/10 data-[active=true]:text-primary dark:data-[active=true]:bg-primary/25",
              className,
            )}
            // Keep the editor selection when a button is pressed with the mouse.
            onMouseDown={(e) => e.preventDefault()}
            onClick={onClick}
            {...props}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>
        {label}
        {keys && <span className="text-background/70">{shortcut(keys)}</span>}
      </TooltipContent>
    </Tooltip>
  );
});

export function ToolGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-0.5">
      {children}
    </div>
  );
}

export function ToolDivider() {
  return <span aria-hidden className="mx-1 hidden h-5 w-px bg-border sm:inline-block" />;
}

const HEX = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i;

export function normalizeHex(value: string): string | null {
  const v = value.trim();
  if (!HEX.test(v)) return null;
  const hex = v.startsWith("#") ? v : `#${v}`;
  return hex.length === 4 ? `#${[...hex.slice(1)].map((c) => c + c).join("")}` : hex.toLowerCase();
}

export interface Swatch {
  name: string;
  value: string;
}

interface ColorPickerProps {
  label: string;
  icon: ReactNode;
  swatches: Swatch[];
  current: string | null;
  resetLabel: string;
  onPick: (color: string) => void;
  onReset: () => void;
}

/** Brand swatches plus a custom hex input, in a popover. */
export function ColorPicker({
  label,
  icon,
  swatches,
  current,
  resetLabel,
  onPick,
  onReset,
}: ColorPickerProps) {
  const [open, setOpen] = useState(false);
  const [hex, setHex] = useState("");
  const [error, setError] = useState<string | null>(null);
  const done = () => {
    setOpen(false);
    setHex("");
    setError(null);
  };
  const applyHex = () => {
    const normalized = normalizeHex(hex);
    if (!normalized) {
      setError("Enter a colour like #C8102E.");
      return;
    }
    onPick(normalized);
    done();
  };
  return (
    <Popover open={open} onOpenChange={(o) => (o ? setOpen(true) : done())}>
      <Tooltip>
        <TooltipTrigger
          render={
            <PopoverTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={label}
                  data-active={current ? "true" : undefined}
                  className="relative text-foreground/80 hover:text-foreground"
                  onMouseDown={(e) => e.preventDefault()}
                />
              }
            />
          }
        >
          {icon}
          <span
            aria-hidden
            className="absolute right-1.5 bottom-0.5 left-1.5 h-0.5 rounded-full bg-border"
            style={current ? { backgroundColor: current } : undefined}
          />
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
      <PopoverContent className="w-60">
        <div role="group" aria-label={`${label} swatches`} className="grid grid-cols-6 gap-1.5">
          {swatches.map((s) => (
            <button
              key={s.value}
              type="button"
              aria-label={`${s.name} ${s.value}`}
              aria-pressed={current?.toLowerCase() === s.value.toLowerCase()}
              title={s.name}
              onClick={() => {
                onPick(s.value);
                done();
              }}
              className="size-7 rounded-md border border-border outline-none focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:ring-2 aria-pressed:ring-ring"
              style={{ backgroundColor: s.value }}
            />
          ))}
        </div>
        <form
          className="mt-3 flex items-start gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            applyHex();
          }}
          noValidate
        >
          <div className="min-w-0 flex-1">
            <Input
              aria-label={`${label} custom hex`}
              placeholder="#C8102E"
              value={hex}
              maxLength={7}
              aria-invalid={error ? true : undefined}
              onChange={(e) => {
                setHex(e.target.value);
                setError(null);
              }}
            />
            {error && (
              <p role="alert" className="mt-1 text-xs text-destructive">
                {error}
              </p>
            )}
          </div>
          <Button type="submit" size="sm" className="h-8">
            Apply
          </Button>
        </form>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="mt-2 w-full justify-start"
          onClick={() => {
            onReset();
            done();
          }}
        >
          <Ban aria-hidden />
          {resetLabel}
        </Button>
      </PopoverContent>
    </Popover>
  );
}
