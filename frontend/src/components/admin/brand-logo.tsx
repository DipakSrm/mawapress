import Image from "next/image";
import { cn } from "@/lib/utils";

/** The logo artwork is dark-on-light, so on dark themes it sits on a white chip. */
export function BrandLogo({
  className,
  priority,
  width = 168,
}: {
  className?: string;
  priority?: boolean;
  width?: number;
}) {
  return (
    <Image
      src="/brand/mawapress-logo.svg"
      alt="MAWAPRESS"
      width={width}
      height={Math.round(width / 4)}
      priority={priority}
      className={cn("h-auto dark:rounded-md dark:bg-white dark:px-2 dark:py-1", className)}
    />
  );
}
