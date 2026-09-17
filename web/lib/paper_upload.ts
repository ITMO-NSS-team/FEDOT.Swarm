import { models, paperModels } from "@/lib/types.ts";
import { InvalidRequest } from "@/lib/validate.ts";

export const paperBackends = ["claude-code", "openrouter"] as const;
export type PaperBackend = (typeof paperBackends)[number];

/** Bounds for a PaperBench run, shared by the JSON and the multipart endpoints: the
 * arguments become a command line either way, so both paths check the same limits. */
export const MIN_SECONDS = 2 * 60;
export const MAX_SECONDS = 20 * 60;
export const MIN_PERSONAS = 1;
export const MAX_PERSONAS = 12;
export const MIN_ROUNDS = 1;
export const MAX_ROUNDS = 100;
export const MAX_SEATS = 4;

/** Upload caps: an arXiv-style LaTeX source tree (many small text files) and a rubric
 * branch that stays readable. */
export const MAX_TEX_FILE_BYTES = 4 * 1024 * 1024;
export const MAX_TEX_TOTAL_BYTES = 16 * 1024 * 1024;
export const MAX_TEX_FILES = 200;
export const MAX_RUBRIC_BYTES = 1024 * 1024;
export const MAX_LABEL_LENGTH = 120;

/** A PDF stands in for the LaTeX source when it is not at hand; parse_pdf.py extracts
 * text only (no OCR), so this is a fallback, not the preferred path (see run.py's own
 * --paper-pdf help). 32 MB comfortably covers a typical paper's PDF, figures included. */
export const MAX_PDF_BYTES = 32 * 1024 * 1024;

/** `%PDF-` is the fixed 5-byte magic every PDF starts with — checked instead of trusting
 * the client's filename or content-type, the same reasoning `sanitizeTexPath` applies to
 * .tex uploads. */
export function isPdf(bytes: Uint8Array): boolean {
  const magic = [0x25, 0x50, 0x44, 0x46, 0x2d]; // "%PDF-"
  return magic.every((b, i) => bytes[i] === b);
}

/** A spend cap only means anything against openrouter's metered backend; claude-code runs
 * on the subscription, so these are left at 0 (no cap) there regardless of what a form
 * sends. Bounds match the free-topic run's own (`lib/validate.ts`). */
export const MAX_USD = 5;
export const MAX_TOKENS = 5_000_000;
export const MAX_REQUESTS = 5000;

/** Response length cap per call (openrouter backend only; see run.py's --max-tokens). A
 * persona reposts a whole file each round, and the judge answers with one verdict per
 * rubric leaf in a single structured reply — a rubric with many leaves needs far more
 * than the default to avoid "Exceeded maximum output retries" from a truncated reply. */
export const MIN_MAX_TOKENS = 256;
export const MAX_MAX_TOKENS = 32_000;
export const DEFAULT_MAX_TOKENS = 4000;

export interface PaperScalars {
  timeoutSeconds: number;
  personas: number;
  rounds: number;
  ranked: boolean;
  seats: number;
  compose: boolean;
  backend: PaperBackend;
  model: string;
  usd: number;
  tokens: number;
  requests: number;
  maxTokens: number;
}

function truthy(value: unknown): boolean {
  return value === true || value === "true" || value === "1";
}

/** The run parameters, whether they arrived as JSON or as multipart form fields. */
export function parsePaperScalars(
  input: Record<string, unknown>,
): PaperScalars {
  const timeout = Number(input.timeoutSeconds);
  if (
    !Number.isFinite(timeout) || timeout < MIN_SECONDS || timeout > MAX_SECONDS
  ) {
    throw new InvalidRequest(
      `Time limit must be between ${MIN_SECONDS / 60} and ${
        MAX_SECONDS / 60
      } minutes`,
    );
  }
  const personas = Math.round(Number(input.personas ?? 1));
  if (
    !Number.isFinite(personas) || personas < MIN_PERSONAS ||
    personas > MAX_PERSONAS
  ) {
    throw new InvalidRequest(
      `Agents must be between ${MIN_PERSONAS} and ${MAX_PERSONAS}`,
    );
  }
  const rounds = Math.round(Number(input.rounds ?? 4));
  if (!Number.isFinite(rounds) || rounds < MIN_ROUNDS || rounds > MAX_ROUNDS) {
    throw new InvalidRequest(
      `Rounds must be between ${MIN_ROUNDS} and ${MAX_ROUNDS}`,
    );
  }
  const seats = Math.round(Number(input.seats ?? 0));
  if (!Number.isFinite(seats) || seats < 0 || seats > MAX_SEATS) {
    throw new InvalidRequest(`Free seats must be between 0 and ${MAX_SEATS}`);
  }
  const backend = String(input.backend ?? "claude-code") as PaperBackend;
  if (!(paperBackends as readonly string[]).includes(backend)) {
    throw new InvalidRequest("Unknown backend");
  }
  const modelChoices = backend === "openrouter" ? models : paperModels;
  const model = String(input.model ?? modelChoices[0]);
  if (!(modelChoices as readonly string[]).includes(model)) {
    throw new InvalidRequest("Unknown model");
  }
  const bounded = (value: unknown, name: string, max: number): number => {
    const n = Number(value ?? 0);
    if (!Number.isFinite(n) || n < 0 || n > max) {
      throw new InvalidRequest(`${name} must be between 0 and ${max}`);
    }
    return n;
  };
  const usd = bounded(input.usd, "usd", MAX_USD);
  const tokens = Math.round(bounded(input.tokens, "tokens", MAX_TOKENS));
  const requests = Math.round(
    bounded(input.requests, "requests", MAX_REQUESTS),
  );
  const maxTokensRaw = Number(input.maxTokens ?? DEFAULT_MAX_TOKENS);
  if (
    !Number.isFinite(maxTokensRaw) || maxTokensRaw < MIN_MAX_TOKENS ||
    maxTokensRaw > MAX_MAX_TOKENS
  ) {
    throw new InvalidRequest(
      `Max tokens must be between ${MIN_MAX_TOKENS} and ${MAX_MAX_TOKENS}`,
    );
  }
  const maxTokens = Math.round(maxTokensRaw);
  // openrouter is metered and has no wall-clock cap of its own (only per-call); with
  // nothing here set, a run is bounded by nothing but --rounds. Same requirement, and the
  // same reasoning, as the free-topic run's own (`lib/validate.ts`).
  if (backend === "openrouter" && !usd && !tokens && !requests) {
    throw new InvalidRequest(
      "Set a limit in dollars, tokens or requests: an uncapped OpenRouter run is not offered here",
    );
  }
  return {
    timeoutSeconds: timeout,
    personas,
    rounds,
    ranked: truthy(input.ranked),
    seats,
    compose: truthy(input.compose),
    backend,
    model,
    // meaningless under claude-code: zeroed rather than trusted, so a stale value left
    // over from switching the backend in the form never reaches the command line
    usd: backend === "openrouter" ? usd : 0,
    tokens: backend === "openrouter" ? tokens : 0,
    requests: backend === "openrouter" ? requests : 0,
    maxTokens,
  };
}

export interface RubricLeaf {
  id: string;
  requirements: string;
  weight: number;
}

/** A hand-typed criterion, entered straight into the form instead of (or alongside) an
 * uploaded rubric.json. */
export interface ManualCriterion {
  requirements: string;
  weight: number;
}

export const MAX_CRITERIA = 100;

/** Custom rubric leaves sent as a JSON array string in the `criteria` form field.
 * Absent or empty input yields no criteria — a rubric file alone is still a valid run. */
export function parseManualCriteria(raw: unknown): ManualCriterion[] {
  if (raw === undefined || raw === null || raw === "") return [];
  let parsed: unknown;
  try {
    parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    throw new InvalidRequest("Custom criteria must be a JSON array");
  }
  if (!Array.isArray(parsed)) {
    throw new InvalidRequest("Custom criteria must be a JSON array");
  }
  if (parsed.length > MAX_CRITERIA) {
    throw new InvalidRequest(
      `At most ${MAX_CRITERIA} custom criteria are accepted`,
    );
  }
  return parsed.map((entry, i) => {
    if (!entry || typeof entry !== "object") {
      throw new InvalidRequest(`Custom criterion ${i + 1} is malformed`);
    }
    const record = entry as Record<string, unknown>;
    const requirements = record["requirements"];
    if (typeof requirements !== "string" || !requirements.trim()) {
      throw new InvalidRequest(
        `Custom criterion ${i + 1} needs requirements text`,
      );
    }
    const weight = record["weight"];
    if (typeof weight !== "number" || !Number.isFinite(weight) || weight <= 0) {
      throw new InvalidRequest(
        `Custom criterion ${i + 1} needs a positive weight`,
      );
    }
    return { requirements: requirements.trim(), weight };
  });
}

/** Combines an uploaded rubric branch with hand-typed criteria into the one branch
 * object `run.py`'s `load_branch` (and `validateRubricBranch` below) expect. Either
 * side may be empty, but not both. With nothing uploaded, the criteria become the
 * leaves of a synthetic root; with an upload too, the upload becomes a sibling branch
 * alongside the new leaves so both sets of requirements are graded together. */
export function buildRubricBranch(
  uploaded: unknown | null,
  manual: ManualCriterion[],
): unknown {
  const manualLeaves = manual.map((c, i) => ({
    id: `custom-${i + 1}`,
    requirements: c.requirements,
    weight: c.weight,
    sub_tasks: [],
  }));
  if (!uploaded && manualLeaves.length === 0) {
    throw new InvalidRequest(
      "Add the rubric branch JSON, custom criteria, or both",
    );
  }
  if (!uploaded) {
    return {
      id: "custom-root",
      requirements: "Custom criteria",
      weight: 1,
      sub_tasks: manualLeaves,
    };
  }
  if (manualLeaves.length === 0) return uploaded;
  return {
    id: "combined-root",
    requirements: "Combined criteria",
    weight: 1,
    sub_tasks: [uploaded, ...manualLeaves],
  };
}

function leavesOf(node: Record<string, unknown>): Record<string, unknown>[] {
  const sub = node["sub_tasks"];
  if (!Array.isArray(sub) || sub.length === 0) return [node];
  return sub.flatMap((child) =>
    child && typeof child === "object"
      ? leavesOf(child as Record<string, unknown>)
      : []
  );
}

/** The same shape `benchmarks/paperbench/run.py`'s `load_branch` demands, checked here
 * so a bad upload is refused at once instead of failing the run minutes later. */
export function validateRubricBranch(value: unknown): RubricLeaf[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new InvalidRequest("Rubric file must hold one JSON object");
  }
  const branch = value as Record<string, unknown>;
  if (
    typeof branch["requirements"] !== "string" || !branch["requirements"].trim()
  ) {
    throw new InvalidRequest(
      "Rubric branch needs a non-empty requirements string",
    );
  }
  const raw = leavesOf(branch);
  if (raw.length === 0) {
    throw new InvalidRequest("Rubric branch has no leaves to grade");
  }
  return raw.map((leaf) => {
    if (typeof leaf["id"] !== "string" || !leaf["id"].trim()) {
      throw new InvalidRequest("Every rubric leaf needs a non-empty string id");
    }
    if (
      typeof leaf["requirements"] !== "string" || !leaf["requirements"].trim()
    ) {
      throw new InvalidRequest(
        `Rubric leaf ${JSON.stringify(leaf["id"])} needs requirements`,
      );
    }
    const weight = leaf["weight"];
    if (typeof weight !== "number" || !Number.isFinite(weight) || weight < 0) {
      throw new InvalidRequest(
        `Rubric leaf ${JSON.stringify(leaf["id"])} needs a weight`,
      );
    }
    return {
      id: leaf["id"] as string,
      requirements: leaf["requirements"] as string,
      weight,
    };
  });
}

/** A path from a folder upload, made safe to join under the run's own inputs
 * directory: no leading slash, no `..` segment, no empty segment, `.tex` only. The
 * browser already only offers `.tex` files (see the file input's `accept`), but a
 * client can send anything over the wire, so this is checked again here rather than
 * trusted. */
export function sanitizeTexPath(path: string): string | null {
  if (!path.toLowerCase().endsWith(".tex")) return null;
  const parts = path.split(/[/\\]+/).filter((p) => p.length > 0);
  if (parts.length === 0 || parts.some((p) => p === "." || p === "..")) {
    return null;
  }
  if (parts[parts.length - 1].toLowerCase() === ".tex") return null;
  return parts.join("/");
}

/** Display name for an uploaded run: the visitor's title, else a name derived from
 * the upload (the source folder's name, or a lone file's). */
export function uploadLabel(title: unknown, fallback: string | null): string {
  const clean = (text: string) =>
    text.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim()
      .slice(0, MAX_LABEL_LENGTH);
  const named = typeof title === "string" ? clean(title) : "";
  if (named) return named;
  if (fallback) {
    const base = clean(fallback.replace(/\.[^.]*$/, "").replace(/[_-]+/g, " "));
    if (base) return base;
  }
  return "upload";
}
