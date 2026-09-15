import { models, type RunRequest } from "@/lib/types.ts";

export class InvalidRequest extends Error {}

function bounded(value: unknown, name: string, min: number, max: number): number {
  const n = typeof value === "number" ? value : Number(value ?? NaN);
  if (!Number.isFinite(n) || n < min || n > max) {
    throw new InvalidRequest(`${name} must be between ${min} and ${max}`);
  }
  return n;
}

/** The arguments become a command line, so every field is checked here rather than trusted
 * and quoted later. Caps are the demonstration's, not the engine's: a visitor should not be
 * able to start a thousand-agent run from a form. */
export function parseRequest(body: unknown): RunRequest {
  if (!body || typeof body !== "object") throw new InvalidRequest("Expected an object");
  const raw = body as Record<string, unknown>;

  const topic = String(raw.topic ?? "").trim();
  if (topic.length < 3 || topic.length > 300) {
    throw new InvalidRequest("Topic must be between 3 and 300 characters");
  }
  if (/[\u0000-\u001f\u007f]/.test(topic)) {
    throw new InvalidRequest("Topic must not contain control characters");
  }

  const model = String(raw.model ?? models[0]);
  if (!(models as readonly string[]).includes(model)) {
    throw new InvalidRequest("Unknown model");
  }

  const request: RunRequest = {
    topic,
    model,
    personas: Math.round(bounded(raw.personas, "personas", 2, 300)),
    rounds: Math.round(bounded(raw.rounds, "rounds", 1, 30)),
    compose: raw.compose === true,
    ranked: raw.ranked === true,
    seats: Math.round(bounded(raw.seats ?? 0, "seats", 0, 8)),
    concurrency: Math.round(bounded(raw.concurrency ?? 2, "concurrency", 1, 8)),
    usd: bounded(raw.usd ?? 0, "usd", 0, 5),
    tokens: Math.round(bounded(raw.tokens ?? 0, "tokens", 0, 5_000_000)),
    requests: Math.round(bounded(raw.requests ?? 0, "requests", 0, 5000)),
  };

  if (!request.usd && !request.tokens && !request.requests) {
    throw new InvalidRequest(
      "Set a limit in dollars, tokens or requests: an uncapped run is not offered here",
    );
  }
  return request;
}
