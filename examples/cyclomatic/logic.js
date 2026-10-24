export function route(request = {}, fallback = 0) {
  const value = request?.nested?.value ?? fallback;
  if (value > 0 && request?.enabled) return value;
  return value ? value : -1;
}
