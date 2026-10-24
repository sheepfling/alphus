export { publicValue as publicValue } from "./api.js";

export const API_URL = "https://example.invalid";

export function register(callback, _context) {
  callback();
}

export function useShadow(value) {
  console.log(value);
  value = value + 1;
  return value;
}

export function useInnerShadow(value) {
  function inner(value) {
    return value + 1;
  }
  return inner(value);
}
