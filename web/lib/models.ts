/** The models the Compose form offers, as pydantic-ai ids. `FEDOTMAS_MODELS` overrides the
 * default pair, comma-separated; `run.py` still needs a catalog price for each. */
export const defaultModels = [
  "openrouter:qwen/qwen3.8-flash",
  "openrouter:qwen/qwen3.7-flash",
];

export function parseModels(raw: string | undefined | null): string[] {
  const listed = (raw ?? "").split(",").map((m) => m.trim()).filter(Boolean);
  return listed.length ? listed : defaultModels;
}

export function models(): string[] {
  return parseModels(Deno.env.get("FEDOTMAS_MODELS"));
}

export function isKnownModel(model: string): boolean {
  return models().includes(model);
}
