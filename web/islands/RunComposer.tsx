import { useState } from "preact/hooks";
import { models, type RunRequest } from "@/lib/types.ts";
import {
  DEFAULT_MAX_TOKENS,
  MAX_CRITERIA,
  MAX_MAX_TOKENS,
  MIN_MAX_TOKENS,
} from "@/lib/paper_upload.ts";

type Axis = "usd" | "tokens" | "requests";
type Mode = "topic" | "paperbench";
type PaperSource = "tex" | "pdf";

interface Criterion {
  requirements: string;
  weight: number;
}

type CriterionRow = Criterion & { key: number };

let criterionSeq = 0;
const newCriterion = (): CriterionRow => ({
  key: criterionSeq++,
  requirements: "",
  weight: 1,
});

const axes: {
  key: Axis;
  label: string;
  unit: string;
  step: number;
  preset: number;
}[] = [
  { key: "usd", label: "Dollars", unit: "USD", step: 0.0001, preset: 0.002 },
  { key: "tokens", label: "Tokens", unit: "tokens", step: 100, preset: 20000 },
  { key: "requests", label: "Requests", unit: "requests", step: 1, preset: 40 },
];

const MIN_MINUTES = 2;
const MAX_MINUTES = 20;
const MIN_PAPER_PERSONAS = 1;
const MAX_PAPER_PERSONAS = 12;
const MIN_PAPER_ROUNDS = 1;
const MAX_PAPER_ROUNDS = 100;

export function RunComposer() {
  const [mode, setMode] = useState<Mode>("topic");

  // Free-topic swarm state
  const [topic, setTopic] = useState(
    "Should frontier AI labs release model weights openly?",
  );
  const [model, setModel] = useState<string>(models[0]);
  const [personas, setPersonas] = useState(12);
  const [axis, setAxis] = useState<Axis>("usd");
  const [amount, setAmount] = useState(0.002);

  // PaperBench state
  const [paperModel, setPaperModel] = useState<string>(models[0]);
  const [paperPersonas, setPaperPersonas] = useState(3);
  const [minutes, setMinutes] = useState(10);
  const [title, setTitle] = useState("");
  const [paperSource, setPaperSource] = useState<PaperSource>("tex");
  const [texFiles, setTexFiles] = useState<File[]>([]);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [rubricFile, setRubricFile] = useState<File | null>(null);
  const [criteria, setCriteria] = useState<CriterionRow[]>([]);
  const [paperAxis, setPaperAxis] = useState<Axis>("usd");
  const [paperAmount, setPaperAmount] = useState(0.002);
  const [maxTokens, setMaxTokens] = useState(DEFAULT_MAX_TOKENS);

  // Shared between both modes: the swarm's own machinery (rounds on a shared feed, an
  // optional ranked feed each, optional free seats a queen may fill, and whether a
  // meta-agent writes the cast) does not change between a free topic and a fixed rubric.
  const [rounds, setRounds] = useState(8);
  const [ranked, setRanked] = useState(true);
  const [seats, setSeats] = useState(0);
  const [compose, setCompose] = useState(true);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = (next: Axis) => {
    setAxis(next);
    setAmount(axes.find((a) => a.key === next)!.preset);
  };

  const pickPaper = (next: Axis) => {
    setPaperAxis(next);
    setPaperAmount(axes.find((a) => a.key === next)!.preset);
  };

  const addCriterion = () => {
    if (criteria.length >= MAX_CRITERIA) return;
    setCriteria([...criteria, newCriterion()]);
  };
  const removeCriterion = (key: number) => {
    setCriteria(criteria.filter((c) => c.key !== key));
  };
  const updateCriterion = (key: number, patch: Partial<Criterion>) => {
    setCriteria(criteria.map((c) => c.key === key ? { ...c, ...patch } : c));
  };

  const startTopic = async () => {
    const request: RunRequest = {
      topic,
      model,
      personas,
      rounds,
      compose,
      ranked,
      seats,
      concurrency: 2,
      usd: axis === "usd" ? amount : 0,
      tokens: axis === "tokens" ? amount : 0,
      requests: axis === "requests" ? amount : 0,
    };
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error ?? "Could not start the run");
    location.href = `/swarm/${body.run.id}`;
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
    const filledCriteria = criteria.filter((c) => c.requirements.trim());
    if (!rubricFile && filledCriteria.length === 0) {
      throw new Error("Attach the rubric branch JSON, add criteria, or both");
    }
    const budget = {
      usd: paperAxis === "usd" ? paperAmount : 0,
      tokens: paperAxis === "tokens" ? paperAmount : 0,
      requests: paperAxis === "requests" ? paperAmount : 0,
    };
    const form = new FormData();
    form.set("title", title);
    form.set("timeoutSeconds", String(minutes * 60));
    form.set("personas", String(paperPersonas));
    form.set("rounds", String(rounds));
    form.set("ranked", String(ranked));
    form.set("seats", String(seats));
    form.set("compose", String(compose));
    form.set("model", paperModel);
    form.set("usd", String(budget.usd));
    form.set("tokens", String(budget.tokens));
    form.set("requests", String(budget.requests));
    form.set("maxTokens", String(maxTokens));
    if (paperSource === "tex") {
      for (const file of texFiles) {
        form.append("tex", file, file.webkitRelativePath || file.name);
      }
    } else {
      form.set("pdf", pdfFile!);
    }
    if (rubricFile) form.set("rubric", rubricFile);
    if (filledCriteria.length > 0) {
      form.set(
        "criteria",
        JSON.stringify(
          filledCriteria.map((c) => ({
            requirements: c.requirements.trim(),
            weight: c.weight,
          })),
        ),
      );
    }
    const response = await fetch("/api/paperbench", {
      method: "POST",
      body: form,
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.error ?? "Could not start the run");
    }
    location.href = `/paperbench/${body.run.id}`;
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

  const current = axes.find((a) => a.key === axis)!;

  return (
    <form class="panel compose" onSubmit={start}>
      <fieldset class="field limit">
        <legend>Target</legend>
        <div class="segmented" role="group" aria-label="Swarm target">
          <button
            type="button"
            aria-pressed={mode === "topic"}
            onClick={() => setMode("topic")}
          >
            Free topic
          </button>
          <button
            type="button"
            aria-pressed={mode === "paperbench"}
            onClick={() => setMode("paperbench")}
          >
            PaperBench
          </button>
        </div>
        <p class="hint">
          {mode === "topic"
            ? "The cast argues a topic you write, on a shared feed, for as many rounds as you allow."
            : "The cast writes code for the paper and rubric branch you upload, on a shared feed, over as many rounds as you allow; a judge scores every voice's last post and keeps the best."}
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
              onInput={(e) => setTopic((e.target as HTMLInputElement).value)}
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
                  onInput={(e) =>
                    setTitle((e.target as HTMLInputElement).value)}
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
                    aria-pressed={paperSource === "tex"}
                    onClick={() => setPaperSource("tex")}
                  >
                    LaTeX folder
                  </button>
                  <button
                    type="button"
                    aria-pressed={paperSource === "pdf"}
                    onClick={() => setPaperSource("pdf")}
                  >
                    PDF
                  </button>
                </div>
                <p class="hint">
                  {paperSource === "tex"
                    ? "Preferred: exact math, no extraction noise."
                    : "Fallback for when the LaTeX source is not at hand — text " +
                      "extraction only (no OCR), so math and layout survive worse " +
                      "than they do from the source."}
                </p>
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
                            .endsWith(
                              ".tex",
                            )
                        );
                        setTexFiles(files);
                      }}
                    />
                    <p class="hint">
                      {texFiles.length > 0
                        ? `${texFiles.length} .tex file${
                          texFiles.length === 1 ? "" : "s"
                        } — ${
                          Math.round(
                            texFiles.reduce((n, f) => n + f.size, 0) / 1024,
                          )
                        } KB`
                        : "Pick the folder holding the paper's .tex source (any " +
                          "entry-file name — the one with \\documentclass is found " +
                          "automatically). Read directly, no OCR: only .tex files are sent."}
                    </p>
                  </label>
                )
                : (
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
                        ? `${pdfFile.name} — ${
                          Math.round(pdfFile.size / 1024)
                        } KB`
                        : "The paper's PDF, e.g. straight from arXiv."}
                    </p>
                  </label>
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
                    ? `${rubricFile.name} — ${
                      Math.round(rubricFile.size / 1024)
                    } KB`
                    : "One branch object: requirements, weight, sub_tasks with leaves. " +
                      "Skip this if you'd rather just write criteria below."}
                </p>
              </label>
              <fieldset class="field upload">
                <legend>Custom criteria (optional)</legend>
                <p class="hint">
                  {rubricFile
                    ? "Added alongside the uploaded rubric branch — both sets are graded together."
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
                      min={0.1}
                      step={0.1}
                      value={c.weight}
                      aria-label="Weight"
                      title="Weight"
                      onInput={(e) =>
                        updateCriterion(c.key, {
                          weight: Number((e.target as HTMLInputElement).value),
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
              <option key={name} value={name}>
                {name.split("/").at(-1)}
              </option>
            ))}
          </select>
        </label>

        <label class="field">
          <span>Agents</span>
          <input
            type="number"
            min={mode === "topic" ? 2 : MIN_PAPER_PERSONAS}
            max={mode === "topic" ? 300 : MAX_PAPER_PERSONAS}
            value={mode === "topic" ? personas : paperPersonas}
            onInput={(e) => {
              const value = Number((e.target as HTMLInputElement).value);
              if (mode === "topic") setPersonas(value);
              else setPaperPersonas(value);
            }}
          />
          {mode === "paperbench" && (
            <p class="hint">
              Voices in the room; each one's last post is scored against the
              rubric and the judge keeps the best.
            </p>
          )}
        </label>

        <label class="field">
          <span>Rounds</span>
          <input
            type="number"
            min={mode === "topic" ? 1 : MIN_PAPER_ROUNDS}
            max={mode === "topic" ? 30 : MAX_PAPER_ROUNDS}
            value={rounds}
            onInput={(e) =>
              setRounds(Number((e.target as HTMLInputElement).value))}
          />
        </label>
        <label class="field">
          <span>Free seats</span>
          <input
            type="number"
            min={0}
            max={mode === "topic" ? 8 : 4}
            value={seats}
            onInput={(e) =>
              setSeats(Number((e.target as HTMLInputElement).value))}
          />
        </label>
      </div>

      {mode === "topic"
        ? (
          <fieldset class="field limit">
            <legend>Stop after</legend>
            <div class="segmented" role="group" aria-label="Limit axis">
              {axes.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  aria-pressed={axis === option.key}
                  onClick={() => pick(option.key)}
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
                value={amount}
                aria-label={`Limit in ${current.unit}`}
                onInput={(e) =>
                  setAmount(Number((e.target as HTMLInputElement).value))}
              />
              <span>{current.unit}</span>
            </div>
            <p class="hint">
              Nothing is called past the limit, so the room goes quiet and the
              run ends with its feed intact. Requests already in flight still
              land.
            </p>
          </fieldset>
        )
        : (
          <>
            <label class="field">
              <span>Time limit</span>
              <input
                type="number"
                min={MIN_MINUTES}
                max={MAX_MINUTES}
                value={minutes}
                onInput={(e) =>
                  setMinutes(Number((e.target as HTMLInputElement).value))}
              />
              <p class="hint">
                Minutes each attempt may spend before its turn is cut off. A
                required spend cap is below — a run is never started without
                one.
              </p>
            </label>
            <fieldset class="field limit">
              <legend>Stop after</legend>
              <div class="segmented" role="group" aria-label="Limit axis">
                {axes.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    aria-pressed={paperAxis === option.key}
                    onClick={() => pickPaper(option.key)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div class="limit-amount">
                <input
                  type="number"
                  min={0}
                  step={axes.find((a) => a.key === paperAxis)!.step}
                  value={paperAmount}
                  aria-label={`Limit in ${
                    axes.find((a) => a.key === paperAxis)!.unit
                  }`}
                  onInput={(e) => setPaperAmount(
                    Number((e.target as HTMLInputElement).value),
                  )}
                />
                <span>{axes.find((a) => a.key === paperAxis)!.unit}</span>
              </div>
              <p class="hint">
                Required — a run with all three at zero is refused. Nothing is
                called past the limit, so the round ends with the feed intact.
              </p>
            </fieldset>
            <label class="field">
              <span>Max tokens</span>
              <input
                type="number"
                min={MIN_MAX_TOKENS}
                max={MAX_MAX_TOKENS}
                value={maxTokens}
                onInput={(e) =>
                  setMaxTokens(
                    Number((e.target as HTMLInputElement).value),
                  )}
              />
              <p class="hint">
                Response length cap per call. A persona reposts a whole file
                each round, and the judge answers with one verdict per rubric
                leaf in a single reply — raise this for a large rubric branch,
                or the judge can run out of room and fail.
              </p>
            </label>
          </>
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
              : " A meta-agent proposes the coders for this rubric. Off uses a plain numbered cast."}
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
