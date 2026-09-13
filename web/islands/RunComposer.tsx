import { useState } from "preact/hooks";
import { models, type RunRequest } from "@/lib/types.ts";

type Axis = "usd" | "tokens" | "requests";

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

export function RunComposer() {
  const [topic, setTopic] = useState(
    "Should frontier AI labs release model weights openly?",
  );
  const [model, setModel] = useState<string>(models[0]);
  const [personas, setPersonas] = useState(12);
  const [rounds, setRounds] = useState(8);
  const [compose, setCompose] = useState(true);
  const [ranked, setRanked] = useState(true);
  const [seats, setSeats] = useState(0);
  const [axis, setAxis] = useState<Axis>("usd");
  const [amount, setAmount] = useState(0.002);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = (next: Axis) => {
    setAxis(next);
    setAmount(axes.find((a) => a.key === next)!.preset);
  };

  const start = async (event: Event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
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
    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error ?? "Could not start the run");
      }
      location.href = `/swarm/${body.run.id}`;
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
      <label class="field">
        <span>Topic</span>
        <input
          value={topic}
          maxLength={300}
          required
          onInput={(e) => setTopic((e.target as HTMLInputElement).value)}
        />
      </label>

      <div class="field-row">
        <label class="field">
          <span>Model</span>
          <select
            value={model}
            onInput={(e) => setModel((e.target as HTMLSelectElement).value)}
          >
            {models.map((name) => (
              <option key={name} value={name}>{name.split("/").at(-1)}</option>
            ))}
          </select>
        </label>
        <label class="field">
          <span>Agents</span>
          <input
            type="number"
            min={2}
            max={300}
            value={personas}
            onInput={(e) =>
              setPersonas(Number((e.target as HTMLInputElement).value))}
          />
        </label>
        <label class="field">
          <span>Rounds</span>
          <input
            type="number"
            min={1}
            max={30}
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
            max={8}
            value={seats}
            onInput={(e) =>
              setSeats(Number((e.target as HTMLInputElement).value))}
          />
        </label>
      </div>

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
          Nothing is called past the limit, so the room goes quiet and the run
          ends with its feed intact. Requests already in flight still land.
        </p>
      </fieldset>

      <div class="toggles">
        <label class="toggle">
          <input
            type="checkbox"
            checked={compose}
            onChange={(e) => setCompose((e.target as HTMLInputElement).checked)}
          />
          <span>
            <strong>Write the cast</strong>
            A meta-agent proposes the agents for this topic. Off uses the
            handwritten cast.
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
            wall. Off still draws the graph, but as affinity the run did not act
            on.
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
