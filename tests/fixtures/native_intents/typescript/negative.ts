import type { UnusedShape } from "./types";

export function use(value: string, unusedCallbackParameter: number): string {
  return value;
  console.log("genuinely unreachable");
}
