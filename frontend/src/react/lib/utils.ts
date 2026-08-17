import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn-style className combiner — required by every future ui/* component. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
