function parametersAtLimit(first, second, { third }) {
  return [first, second, third];
}

function parametersOverLimit(first, second, third = 3, fourth = 4) {
  return [first, second, third, fourth];
}

function nestedCallbacksAtLimit(values) {
  return values.map((value) => Promise.resolve(value));
}

function nestedCallbacksOverLimit(values) {
  return values.map((value) => [value].map((nested) => Promise.resolve(nested)));
}

function statementBoundary(enabled) {
  const first = 1;
  const second = 2;
  if (enabled) return first + second;
}

function statementOverLimit(enabled) {
  const first = 1;
  const second = 2;
  const third = 3;
  if (enabled) return first + second + third;
}

function depthBoundary(enabled) {
  if (enabled) return true;
  return false;
}

function depthOverLimit(enabled, other) {
  if (enabled) {
    if (other) return true;
  }
  return false;
}
