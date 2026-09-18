import { useEffect, useState } from "preact/hooks";

interface Root {
  key: string;
  label: string;
}

interface Listed {
  path: string;
  bytes: number;
}

interface Round {
  round: number;
  report: string;
  files: string[];
  cost: number;
  seconds: number;
  timedOut: boolean;
  toolCalls: Record<string, number>;
  tokens: Record<string, number>;
  error: string | null;
}

interface Props {
  id: string;
  roots: Root[];
  root: string;
  onRoot: (root: string) => void;
}

const size = (bytes: number) =>
  bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  const text = await response.text();
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`Unexpected reply (${response.status})`);
  }
  if (!response.ok) {
    throw new Error(
      String(
        (body as { error?: string }).error ??
          `Request failed (${response.status})`,
      ),
    );
  }
  return body as T;
}

/** Files of one root of a run, read straight off the run's directories, plus every round
 * a voice worked when the root is a workspace. */
export function FileBrowser({ id, roots, root, onRoot }: Props) {
  const [files, setFiles] = useState<Listed[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [rounds, setRounds] = useState<Round[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"files" | "rounds">("files");

  const base = `/api/paperbench/${id}`;
  const voice = root.startsWith("ws/") ? root.slice(3) : null;

  useEffect(() => {
    let stale = false;
    setFiles(null);
    setSelected(null);
    setContent(null);
    setError(null);
    setView("files");
    getJson<{ files: Listed[] }>(
      `${base}/files?root=${encodeURIComponent(root)}`,
    )
      .then((body) => {
        if (stale) return;
        setFiles(body.files);
        const first = body.files.find((f) =>
          /\.(py|md|txt|toml|cfg|yaml|yml|json)$/.test(f.path)
        );
        if (first) open(first.path);
      })
      .catch((failure) => {
        if (!stale) {
          setError(failure instanceof Error ? failure.message : "Unavailable");
        }
      });
    if (voice) {
      getJson<{ rounds: Record<string, Round[]> }>(`${base}/trace`)
        .then((body) => {
          if (!stale) setRounds(body.rounds[voice] ?? []);
        })
        .catch(() => {
          if (!stale) setRounds([]);
        });
    } else {
      setRounds(null);
    }
    return () => {
      stale = true;
    };
  }, [base, root]);

  const open = async (path: string) => {
    setSelected(path);
    setContent(null);
    setError(null);
    try {
      const response = await fetch(
        `${base}/file?root=${encodeURIComponent(root)}&path=${
          encodeURIComponent(path)
        }`,
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(
          body.error ?? `Cannot show this file (${response.status})`,
        );
      }
      setContent(await response.text());
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Unavailable");
    }
  };

  return (
    <div class="file-browser">
      <div class="file-browser-side">
        <label class="field">
          <span>Root</span>
          <select
            value={root}
            onInput={(e) => onRoot((e.target as HTMLSelectElement).value)}
          >
            {roots.map((r) => (
              <option key={r.key} value={r.key}>{r.label}</option>
            ))}
          </select>
        </label>
        {voice && (
          <div class="segmented" role="group" aria-label="View">
            <button
              type="button"
              aria-pressed={view === "files"}
              onClick={() => setView("files")}
            >
              Files
            </button>
            <button
              type="button"
              aria-pressed={view === "rounds"}
              onClick={() => setView("rounds")}
            >
              Rounds{rounds ? ` (${rounds.length})` : ""}
            </button>
          </div>
        )}
        {view === "files" && (
          <ul class="file-tree">
            {files === null && !error && (
              <li class="empty skeleton-text">Listing</li>
            )}
            {files?.length === 0 && <li class="empty">No files here.</li>}
            {files?.map((file) => (
              <li key={file.path}>
                <button
                  type="button"
                  class={selected === file.path ? "selected" : undefined}
                  onClick={() => open(file.path)}
                >
                  <span class="file-name">{file.path}</span>
                  <span class="file-lines">{size(file.bytes)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {voice && (
          <a
            class="hint"
            href={`${base}/download?root=${encodeURIComponent(root)}`}
            download
          >
            Download this workspace as zip
          </a>
        )}
      </div>
      <div class="file-browser-main">
        {view === "rounds" && voice
          ? (
            <ol class="rounds">
              {rounds?.length === 0 && (
                <li class="empty">No rounds recorded.</li>
              )}
              {rounds?.map((r) => (
                <li key={r.round}>
                  <h3>
                    Round {r.round + 1} · {Math.round(r.seconds)}s ·{" "}
                    {Object.values(r.toolCalls ?? {}).reduce(
                      (a, b) => a + b,
                      0,
                    )} tool calls · ${r.cost.toFixed(4)}
                    {r.timedOut ? " · timed out" : ""}
                    {r.error ? ` · ${r.error}` : ""}
                  </h3>
                  <p class="round-report">{r.report}</p>
                  {r.files.length > 0 && (
                    <p class="hint">Changed: {r.files.join(", ")}</p>
                  )}
                </li>
              ))}
            </ol>
          )
          : error
          ? <p class="form-error" role="status">{error}</p>
          : selected === null
          ? <p class="empty">Pick a file.</p>
          : content === null
          ? <p class="empty skeleton-text">Loading {selected}</p>
          : (
            <>
              <p class="code-path">{selected}</p>
              <pre class="code-view"><code>{content}</code></pre>
            </>
          )}
      </div>
    </div>
  );
}
