#include <string>

[[maybe_unused]] static const int legacyID = 1;

int register_callback(int value, [[maybe_unused]] int callbackContext) {
  return value;
}

int use_shadow(int value) {
  int other = value;
  other = other + 1;
  return other;
}
