export type PlaygroundMode = "chat" | "responses" | "completions" | "embeddings";

export function validateTemperature(value: string, mode: PlaygroundMode) {
  if (mode === "embeddings") return null;
  const parsed = Number(value);
  if (!value.trim() || !Number.isFinite(parsed)) return "Enter a temperature.";
  if (parsed < 0 || parsed > 2) return "Temperature must be between 0 and 2.";
  return null;
}

export function validateMaxTokens(value: string, mode: PlaygroundMode) {
  if (mode === "embeddings") return null;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) return "Max tokens must be a positive integer.";
  return null;
}
