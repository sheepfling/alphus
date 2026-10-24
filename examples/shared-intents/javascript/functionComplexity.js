export function chooseResult(value, mode, fallback) {
  if (mode === "strict") {
    if (value > 10) {
      return value;
    }
    return fallback;
  }
  if (mode === "clamp") {
    return Math.max(value, 0);
  }
  return fallback;
}
