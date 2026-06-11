export function isWithinBcryptByteLimit(password: string) {
  return new TextEncoder().encode(password).length <= 72;
}
