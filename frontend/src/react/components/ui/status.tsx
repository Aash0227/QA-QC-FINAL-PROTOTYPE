import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

import type { StageStatus } from "@/types/pipeline";
import type { badgeVariants } from "@/components/ui/badge";

/** Spinner used by active pipeline stages and any in-flight action. */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin", className)} aria-hidden="true" />;
}

type BadgeVariant = NonNullable<Parameters<typeof badgeVariants>[0]>["variant"];

/** Stage status → Badge variant. The one mapping every future status UI uses. */
export const STATUS_VARIANT: Record<StageStatus, BadgeVariant> = {
  pending: "secondary",
  running: "default",
  done: "success",
  failed: "destructive",
  skipped: "outline",
};

export function statusVariant(status: StageStatus): BadgeVariant {
  return STATUS_VARIANT[status];
}
