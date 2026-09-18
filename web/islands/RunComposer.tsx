import { useState } from "preact/hooks";
import type { RunRequest } from "@/lib/types.ts";
import {
  DEFAULT_CONCURRENCY,
  DEFAULT_MAX_TOKENS,
  DEFAULT_ROUND_MINUTES,
  DEFAULT_SECONDS,
  DEFAULT_STEPS,
  MAX_CONCURRENCY,
  MAX_CRITERIA,
  MAX_MAX_TOKENS,
  MAX_ROUND_MINUTES,
  MAX_SEED,
  MAX_STEPS,
  MIN_CONCURRENCY,
  MIN_MAX_TOKENS,
  MIN_ROUND_MINUTES,
  MIN_STEPS,
  PDF_ENGINES,
} from "@/lib/paper_upload.ts";

type Axis = "usd" | "tokens" | "requests";
type Mode = "topic" | "paperbench";
type PaperSource = "tex" | "pdf";

interface CriterionRow {
  key: number;
  requirements: string;
  weight: string;
}

let criterionSeq = 0;
const newCriterion = (): CriterionRow => ({
  key: criterionSeq++,
  requirements: "",
  weight: "1",
});

const axes: { key: Axis; label: string; unit: string; step: number }[] = [
  { key: "usd", label: "Dollars", unit: "USD", step: 0.01 },
  { key: "tokens", label: "Tokens", unit: "tokens", step: 1000 },
  { key: "requests", label: "Requests", unit: "requests", step: 1 },
];

const presets: Record<Mode, Record<Axis, string>> = {
  topic: { usd: "0.01", tokens: "50000", requests: "60" },
  paperbench: { usd: "1.5", tokens: "3000000", requests: "600" },
};

const MIN_PAPER_PERSONAS = 1;
const MAX_PAPER_PERSONAS = 12;
const MIN_PAPER_ROUNDS = 1;
const MAX_PAPER_ROUNDS = 100;

/** A numeric field keeps its text while being typed and is parsed on submit, so a
 * half-typed value never turns into NaN mid-edit. */
function number(
  draft: string,
  name: string,
  min: number,
  max: number,
  integer = true,
): number {
  const value = Number(draft.trim());
  if (draft.trim() === "" || !Number.isFinite(value)) {
    throw new Error(`${name} needs a number`);
  }
  if (value < min || value > max) {
    throw new Error(`${name} must be between ${min} and ${max}`);
  }
  return integer ? Math.round(value) : value;
}

async function send(
  url: string,
  init: RequestInit,
): Promise<Record<string, unknown>> {
  const response = await fetch(url, init);
  const text = await response.text();
  let body: Record<string, unknown>;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(
      response.ok
        ? "The server sent an unexpected reply"
        : `The server refused the request (${response.status})`,
    );
  }
  if (!response.ok) {
    throw new Error(String(body.error ?? "Could not start the run"));
  }
  return body;
}

export function RunComposer({ models }: { models: string[] }) {
  const [mode, setMode] = useState<Mode>("paperbench");

  // Free-topic swarm
  const [topic, setTopic] = useState(
    "Should frontier AI labs release model weights openly?",
  );
  const [model, setModel] = useState<string>(models[0]);
  const [personas, setPersonas] = useState("12");
  const [rounds, setRounds] = useState("8");
  const [seats, setSeats] = useState("0");
  const [axis, setAxis] = useState<Axis>("usd");
  const [amount, setAmount] = useState(presets.topic.usd);

  // PaperBench
  const [paperModel, setPaperModel] = useState<string>(models[0]);
  const [paperPersonas, setPaperPersonas] = useState("8");
  const [paperRounds, setPaperRounds] = useState("9");
  const [paperSeats, setPaperSeats] = useState("0");
  const [roundMinutes, setRoundMinutes] = useState(
    String(DEFAULT_ROUND_MINUTES),
  );
  const [steps, setSteps] = useState(String(DEFAULT_STEPS));
  const [concurrency, setConcurrency] = useState(String(DEFAULT_CONCURRENCY));
  const [seed, setSeed] = useState(String(Math.floor(Math.random() * 100000)));
  const [pdfEngine, setPdfEngine] = useState<string>(PDF_ENGINES[0]);
  const [title, setTitle] = useState("");
  const [paperSource, setPaperSource] = useState<PaperSource>("pdf");
  const [texFiles, setTexFiles] = useState<File[]>([]);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [rubricFile, setRubricFile] = useState<File | null>(null);
  const [criteria, setCriteria] = useState<CriterionRow[]>([]);
  const [paperAxis, setPaperAxis] = useState<Axis>("usd");
  const [paperAmount, setPaperAmount] = useState(presets.paperbench.usd);
  const [maxTokens, setMaxTokens] = useState(String(DEFAULT_MAX_TOKENS));

  // Shared
  const [ranked, setRanked] = useState(true);
  const [compose, setCompose] = useState(true);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = (next: Axis) => {
    setAxis(next);
    setAmount(presets.topic[next]);
  };
  const pickPaper = (next: Axis) => {
    setPaperAxis(next);
    setPaperAmount(presets.paperbench[next]);
  };

  const addCriterion = () => {
    if (criteria.length >= MAX_CRITERIA) return;
    setCriteria([...criteria, newCriterion()]);
  };
  const removeCriterion = (key: number) =>
    setCriteria(criteria.filter((c) => c.key !== key));
  const updateCriterion = (key: number, patch: Partial<CriterionRow>) =>
    setCriteria(criteria.map((c) => c.key === key ? { ...c, ...patch } : c));

  const capOf = (which: Axis, draft: string) => {
    const unit = axes.find((a) => a.key === which)!.unit;
    const cap = number(
      draft,
      `Limit in ${unit}`,
      0,
      which === "usd" ? 5 : 5_000_000,
      which !== "usd",
    );
    if (cap <= 0) throw new Error("Set a limit above zero");
    return cap;
  };

  const startTopic = async () => {
    const cap = capOf(axis, amount);
    const request: RunRequest = {
      topic,
      model,
      personas: number(personas, "Agents", 2, 300),
      rounds: number(rounds, "Rounds", 1, 30),
      compose,
      ranked,
      seats: number(seats, "Free seats", 0, 8),
      concurrency: 2,
      usd: axis === "usd" ? cap : 0,
      tokens: axis === "tokens" ? cap : 0,
      requests: axis === "requests" ? cap : 0,
    };
    const body = await send("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    });
    location.href = `/swarm/${(body.run as { id: string }).id}`;
  };

  const startPaperBench = async () => {
    if (paperSource === "tex" && texFiles.length === 0) {
      throw new Error(
        "Attach the paper's LaTeX source (a folder of .tex files)",
      );
    }
    if (paperSource === "pdf" && !pdfFile) {
      throw new Error("Attach the paper's PDF");
    }
    const filled = criteria.filter((c) => c.requirements.trim());
    if (!rubricFile && filled.length === 0) {
      throw new Error("Attach the rubric branch JSON, add criteria, or both");
    }
    const parsedCriteria = filled.map((c, i) => ({
      requirements: c.requirements.trim(),
      weight: number(
        c.weight,
        `Weight of criterion ${i + 1}`,
        0.01,
        1000,
        false,
      ),
    }));
    const cap = capOf(paperAxis, paperAmount);
    const form = new FormData();
    form.set("title", title);
    form.set("timeoutSeconds", String(DEFAULT_SECONDS));
    form.set(
      "personas",
      String(
        number(paperPersonas, "Agents", MIN_PAPER_PERSONAS, MAX_PAPER_PERSONAS),
      ),
    );
    form.set(
      "rounds",
      String(number(paperRounds, "Rounds", MIN_PAPER_ROUNDS, MAX_PAPER_ROUNDS)),
    );
    form.set("ranked", String(ranked));
    form.set("seats", String(number(paperSeats, "Free seats", 0, 4)));
    form.set("compose", String(compose));
    form.set("model", paperModel);
    form.set("usd", String(paperAxis === "usd" ? cap : 0));
    form.set("tokens", String(paperAxis === "tokens" ? cap : 0));
    form.set("requests", String(paperAxis === "requests" ? cap : 0));
    form.set(
      "maxTokens",
      String(number(maxTokens, "Max tokens", MIN_MAX_TOKENS, MAX_MAX_TOKENS)),
    );
    form.set(
      "roundMinutes",
      String(
        number(
          roundMinutes,
          "Minutes per round",
          MIN_ROUND_MINUTES,
          MAX_ROUND_MINUTES,
          false,
        ),
      ),
    );
    form.set(
      "steps",
      String(number(steps, "Steps per round", MIN_STEPS, MAX_STEPS)),
    );
    form.set(
      "concurrency",
      String(
        number(concurrency, "Agents at once", MIN_CONCURRENCY, MAX_CONCURRENCY),
      ),
    );
    form.set("seed", String(number(seed, "Seed", 0, MAX_SEED)));
    form.set("pdfEngine", pdfEngine);
    form.set("workers", "opencode");
    if (paperSource === "tex") {
      for (const file of texFiles) {
        form.append("tex", file, file.webkitRelativePath || file.name);
      }
    } else {
      form.set("pdf", pdfFile!);
    }
    if (rubricFile) form.set("rubric", rubricFile);
    if (parsedCriteria.length > 0) {
      form.set("criteria", JSON.stringify(parsedCriteria));
    }
    const body = await send("/api/paperbench", { method: "POST", body: form });
    location.href = `/paperbench/${(body.run as { id: string }).id}`;
  };

  const start = async (event: Event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (mode === "topic" ? startTopic() : startPaperBench());
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not start the run",
      );
      setBusy(false);
    }
  };

  const current = axes.find((a) =>
    a.key === (mode === "topic" ? axis : paperAxis)
  )!;
  const text = (setter: (v: string) => void) => (e: Event) =>
    setter((e.target as HTMLInputElement).value);

  return (
    <form class="panel compose" onSubmit={start}>
      <fieldset class="field limit">
        <legend>Target</legend>
        <div class="segmented" role="group" aria-label="Swarm target">
          <button
            type="button"
            aria-pressed={mode === "paperbench"}
            onClick={() => setMode("paperbench")}
          >
            PaperBench
          </button>
          <button
            type="button"
            aria-pressed={mode === "topic"}
            onClick={() => setMode("topic")}
          >
            Free topic
          </button>
        </div>
        <p class="hint">
          {mode === "topic"
            ? "The cast argues a topic you write, on a shared feed, for as many rounds as you allow."
            : "Every voice is an OpenCode coding agent in its own workspace, seeded with the paper and the rubric. Each round it works for a few minutes, commits, and posts a short report to the feed; a judge reads every workspace at the end and keeps the best."}
        </p>
      </fieldset>

      {mode === "topic"
        ? (
          <label class="field">
            <span>Topic</span>
            <input
              value={topic}
              maxLength={300}
              required
              onInput={text(setTopic)}
            />
          </label>
        )
        : (
          <div class="field">
            <span>Paper</span>
            <fieldset class="field upload">
              <legend>Upload</legend>
              <label class="field">
                <span>Title (optional)</span>
                <input
                  value={title}
                  maxLength={120}
                  placeholder="Shown on the run page"
                  onInput={text(setTitle)}
                />
              </label>
              <fieldset class="field limit">
                <legend>Source</legend>
                <div
                  class="segmented"
                  role="group"
                  aria-label="Paper source format"
                >
                  <button
                    type="button"
                    aria-pressed={paperSource === "pdf"}
                    onClick={() => setPaperSource("pdf")}
                  >
                    PDF
                  </button>
                  <button
                    type="button"
                    aria-pressed={paperSource === "tex"}
                    onClick={() => setPaperSource("tex")}
                  >
                    LaTeX folder
                  </button>
                </div>
              </fieldset>
              {paperSource === "tex"
                ? (
                  <label class="field">
                    <span>Paper LaTeX source</span>
                    <input
                      type="file"
                      {
                        // deno-lint-ignore no-explicit-any
                        ...({ webkitdirectory: true, directory: true } as any)
                      }
                      multiple
                      onChange={(e) => {
                        const files = Array.from(
                          (e.target as HTMLInputElement).files ?? [],
                        ).filter((f) =>
                          (f.webkitRelativePath || f.name).toLowerCase()
                            .endsWith(".tex")
                        );
                        setTexFiles(files);
                      }}
                    />
                    <p class="hint">
                      {texFiles.length > 0
                        ? `${texFiles.length} .tex file${
                          texFiles.length === 1 ? "" : "s"
                        }, ${
                          Math.round(
                            texFiles.reduce((n, f) => n + f.size, 0) / 1024,
                          )
                        } KB`
                        : "Pick the folder holding the paper's .tex source. Exact math, no extraction; only .tex files are sent."}
                    </p>
                  </label>
                )
                : (
                  <>
                    <label class="field">
                      <span>Paper PDF</span>
                      <input
                        type="file"
                        accept=".pdf,application/pdf"
                        onChange={(e) =>
                          setPdfFile(
                            (e.target as HTMLInputElement).files?.[0] ?? null,
                          )}
                      />
                      <p class="hint">
                        {pdfFile
                          ? `${pdfFile.name}, ${
                            Math.round(pdfFile.size / 1024)
                          } KB`
                          : "The paper's PDF, e.g. straight from arXiv."}
                      </p>
                    </label>
                    <label class="field">
                      <span>PDF engine</span>
                      <select
                        value={pdfEngine}
                        onInput={(e) =>
                          setPdfEngine((e.target as HTMLSelectElement).value)}
                      >
                        <option value="marker">
                          marker: layout, tables, equations, OCR (about a
                          minute)
                        </option>
                        <option value="pymupdf">
                          pymupdf: text layer only (seconds)
                        </option>
                      </select>
                    </label>
                  </>
                )}
              <label class="field">
                <span>Rubric branch JSON (optional)</span>
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={(e) =>
                    setRubricFile(
                      (e.target as HTMLInputElement).files?.[0] ?? null,
                    )}
                />
                <p class="hint">
                  {rubricFile
                    ? `${rubricFile.name}, ${
                      Math.round(rubricFile.size / 1024)
                    } KB`
                    : "One branch object: requirements, weight, sub_tasks with leaves. Skip this if you'd rather just write criteria below."}
                </p>
              </label>
              <fieldset class="field upload">
                <legend>Custom criteria (optional)</legend>
                <p class="hint">
                  {rubricFile
                    ? "Added alongside the uploaded rubric branch; both sets are graded together."
                    : "Each line becomes its own graded leaf, with the weight it carries in the score."}
                </p>
                {criteria.length > 0 && (
                  <div class="field-row criterion-row criterion-header">
                    <span>Requirement</span>
                    <span>Weight</span>
                    <span />
                  </div>
                )}
                {criteria.map((c) => (
                  <div key={c.key} class="field-row criterion-row">
                    <input
                      class="criterion-text"
                      value={c.requirements}
                      placeholder="e.g. The model correctly samples noise"
                      maxLength={500}
                      onInput={(e) =>
                        updateCriterion(c.key, {
                          requirements: (e.target as HTMLInputElement).value,
                        })}
                    />
                    <input
                      type="number"
                      class="criterion-weight"
                      min={0.01}
                      step={0.1}
                      value={c.weight}
                      aria-label="Weight"
                      title="Weight"
                      onInput={(e) =>
                        updateCriterion(c.key, {
                          weight: (e.target as HTMLInputElement).value,
                        })}
                    />
                    <button
                      type="button"
                      class="icon-button"
                      aria-label="Remove criterion"
                      onClick={() => removeCriterion(c.key)}
                    >
                      ×
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  class="secondary-button"
                  onClick={addCriterion}
                  disabled={criteria.length >= MAX_CRITERIA}
                >
                  + Add criterion
                </button>
              </fieldset>
            </fieldset>
          </div>
        )}

      <div class="field-row">
        <label class="field">
          <span>Model</span>
          <select
            value={mode === "topic" ? model : paperModel}
            onInput={(e) => {
              const value = (e.target as HTMLSelectElement).value;
              if (mode === "topic") setModel(value);
              else setPaperModel(value);
            }}
          >
            {models.map((name) => (
              <option key={name} value={name}>{name.split("/").at(-1)}</option>
            ))}
          </select>
          {mode === "paperbench" && (
            <p class="hint">
              Drives the composer, the judge and the coding agents.
            </p>
          )}
        </label>

        <label class="field">
          <span>Agents</span>
          <input
            type="number"
            min={mode === "topic" ? 2 : MIN_PAPER_PERSONAS}
            max={mode === "topic" ? 300 : MAX_PAPER_PERSONAS}
            value={mode === "topic" ? personas : paperPersonas}
            onInput={text(mode === "topic" ? setPersonas : setPaperPersonas)}
          />
          {mode === "paperbench" && (
            <p class="hint">Voices in the room, one workspace each.</p>
          )}
        </label>

        <label class="field">
          <span>Rounds</span>
          <input
            type="number"
            min={mode === "topic" ? 1 : MIN_PAPER_ROUNDS}
            max={mode === "topic" ? 30 : MAX_PAPER_ROUNDS}
            value={mode === "topic" ? rounds : paperRounds}
            onInput={text(mode === "topic" ? setRounds : setPaperRounds)}
          />
        </label>
        <label class="field">
          <span>Free seats</span>
          <input
            type="number"
            min={0}
            max={mode === "topic" ? 8 : 4}
            value={mode === "topic" ? seats : paperSeats}
            onInput={text(mode === "topic" ? setSeats : setPaperSeats)}
          />
        </label>
      </div>

      {mode === "paperbench" && (
        <div class="field-row">
          <label class="field">
            <span>Minutes per round</span>
            <input
              type="number"
              min={MIN_ROUND_MINUTES}
              max={MAX_ROUND_MINUTES}
              step={0.5}
              value={roundMinutes}
              onInput={text(setRoundMinutes)}
            />
            <p class="hint">
              An agent's session is aborted past this; its files stay.
            </p>
          </label>
          <label class="field">
            <span>Steps per round</span>
            <input
              type="number"
              min={MIN_STEPS}
              max={MAX_STEPS}
              value={steps}
              onInput={text(setSteps)}
            />
            <p class="hint">Tool calls an agent may make in one round.</p>
          </label>
          <label class="field">
            <span>Agents at once</span>
            <input
              type="number"
              min={MIN_CONCURRENCY}
              max={MAX_CONCURRENCY}
              value={concurrency}
              onInput={text(setConcurrency)}
            />
            <p class="hint">A round lasts as long as its slowest agent.</p>
          </label>
          <label class="field">
            <span>Seed</span>
            <input
              type="number"
              min={0}
              max={MAX_SEED}
              value={seed}
              onInput={text(setSeed)}
            />
            <p class="hint">
              Fixes who is sampled each round, not what they write.
            </p>
          </label>
        </div>
      )}

      <fieldset class="field limit">
        <legend>Stop after</legend>
        <div class="segmented" role="group" aria-label="Limit axis">
          {axes.map((option) => (
            <button
              key={option.key}
              type="button"
              aria-pressed={(mode === "topic" ? axis : paperAxis) ===
                option.key}
              onClick={() => (mode === "topic" ? pick : pickPaper)(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div class="limit-amount">
          <input
            type="number"
            min={0}
            step={current.step}
            value={mode === "topic" ? amount : paperAmount}
            aria-label={`Limit in ${current.unit}`}
            onInput={text(mode === "topic" ? setAmount : setPaperAmount)}
          />
          <span>{current.unit}</span>
        </div>
        <p class="hint">
          Required. Nothing is called past the limit, so the run ends with its
          store and workspaces intact. Sessions already in flight still finish
          their round.
        </p>
      </fieldset>

      {mode === "paperbench" && (
        <label class="field">
          <span>Max tokens</span>
          <input
            type="number"
            min={MIN_MAX_TOKENS}
            max={MAX_MAX_TOKENS}
            value={maxTokens}
            onInput={text(setMaxTokens)}
          />
          <p class="hint">
            Response length cap per composer and judge call. The judge grades
            the rubric in slices of twenty leaves, so the default is enough for
            any branch.
          </p>
        </label>
      )}

      <div class="toggles">
        <label class="toggle">
          <input
            type="checkbox"
            checked={compose}
            onChange={(e) => setCompose((e.target as HTMLInputElement).checked)}
          />
          <span>
            <strong>Write the cast</strong>
            {mode === "topic"
              ? " A meta-agent proposes the agents for this topic. Off uses the handwritten cast."
              : " A meta-agent proposes the coders for this paper. Off uses a plain numbered cast."}
          </span>
        </label>
        <label class="toggle">
          <input
            type="checkbox"
            checked={ranked}
            onChange={(e) => setRanked((e.target as HTMLInputElement).checked)}
          />
          <span>
            <strong>A feed each</strong>
            Every agent reads its own ranking of the posts instead of one shared
            wall.
          </span>
        </label>
      </div>

      {error && <p class="form-error" role="alert">{error}</p>}

      <button class="primary-button" type="submit" disabled={busy}>
        {busy ? "Starting…" : "Start the swarm"}
      </button>
    </form>
  );
}
