int choose_result(int value, int mode, int fallback) {
  if (mode == 1) {
    if (value > 10) {
      return value;
    }
    return fallback;
  }
  if (mode == 2) {
    if (value < 0) {
      return 0;
    }
    return value;
  }
  return fallback;
}
