export function optionalAndDefault(value = 0, source = {}) {
  const item = source?.nested?.value ?? value;
  if (item > 0 && value) return item;
  return item ? item : -1;
}

export function nestedAndSwitch(value) {
  try {
    if (value > 0) {
      switch (value) {
        case 1:
        case 2:
          return 1;
        default:
          return value > 5 ? 5 : value;
      }
    }
  } catch (error) {
    if (error) return -1;
  }
  return 0;
}
