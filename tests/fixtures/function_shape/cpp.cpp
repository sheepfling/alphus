#define TWO_DECLARATIONS(value) int first = 1; int second = (value)

template <typename T>
T template_boundary(T first, T second) {
  return first + second;
}

int parameter_boundary(int first, int second, int third) {
  return first + second + third;
}

int parameter_over_limit(int first, int second, int third, int fourth) {
  return first + second + third + fourth;
}

int statement_boundary() {
  int first = 1;
  int second = 2;
  return first + second;
}

int statement_over_limit() {
  int first = 1;
  int second = 2;
  int third = 3;
  return first + second + third;
}

int macro_statement_case(int value) {
  TWO_DECLARATIONS(value);
  return first + second;
}

int nesting_boundary(bool enabled) {
  if (enabled) return 1;
  return 0;
}

int nesting_over_limit(bool enabled, bool other) {
  if (enabled) {
    if (other) return 1;
  }
  return 0;
}

struct Initialized {
  int value;
  explicit Initialized(int input) : value(input) {}
};
