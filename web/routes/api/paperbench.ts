import { dirname, join } from "node:path";
import { create, list, type PaperInputs } from "@/lib/paperbench.ts";
import { newRunId, paperPaths } from "@/lib/paths.ts";
import {
  MAX_RUBRIC_BYTES,
  MAX_TEX_FILE_BYTES,
  MAX_TEX_FILES,
  MAX_TEX_TOTAL_BYTES,
  parsePaperScalars,
  sanitizeTexPath,
  uploadLabel,
  validateRubricBranch,
} from "@/lib/paper_upload.ts";
import { define } from "@/utils.ts";

function failed(error: unknown, status: number) {
  const message = error instanceof Error
    ? error.message
    : "Could not start the run";
  return Response.json({ error: message }, { status });
}

function start(
  paper: string,
  scalars: ReturnType<typeof parsePaperScalars>,
  inputs: PaperInputs = {},
) {
  try {
    return Response.json({
      run: create(paper, scalars, inputs),
    }, { status: 201 });
  } catch (error) {
    return failed(error, 502);
  }
}

/** The folder's own name if the upload was nested (a browser's `webkitdirectory` picker
 * sends each file's name as `<folder>/<...>/<file>.tex`), else the lone file's. */
function folderLabel(relPaths: string[]): string | null {
  if (relPaths.length === 0) return null;
  const segments = relPaths[0].split("/");
  return segments.length > 1 ? segments[0] : segments[segments.length - 1];
}

/** A run from uploaded files: the rubric JSON is required, a LaTeX source with it — one
 * `.tex` file or a whole folder of them (an arXiv-style source tree, `main.tex` plus
 * whatever it `\input`s) sent as repeated `tex` fields, each carrying its path relative
 * to the folder as its filename. Everything is saved under fixed names beside the run so
 * the client's own paths never touch disk unsanitized. */
async function postUpload(req: Request) {
  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return Response.json({ error: "Expected a multipart form" }, {
      status: 400,
    });
  }
  const fields: Record<string, unknown> = {};
  for (const [key, value] of form) {
    if (typeof value === "string") fields[key] = value;
  }
  let scalars: ReturnType<typeof parsePaperScalars>;
  try {
    scalars = parsePaperScalars(fields);
  } catch (error) {
    return failed(error, 422);
  }

  const rubricFile = form.get("rubric");
  if (!(rubricFile instanceof File) || rubricFile.size === 0) {
    return Response.json(
      { error: "Attach the rubric branch JSON to start a custom run" },
      { status: 422 },
    );
  }
  if (rubricFile.size > MAX_RUBRIC_BYTES) {
    return Response.json({ error: "Rubric file must be under 1 MB" }, {
      status: 422,
    });
  }
  let rubric: unknown;
  try {
    rubric = JSON.parse(await rubricFile.text());
  } catch {
    return Response.json({ error: "Rubric file is not valid JSON" }, {
      status: 422,
    });
  }
  try {
    validateRubricBranch(rubric);
  } catch (error) {
    return failed(error, 422);
  }

  const texFiles = form.getAll("tex").filter((f): f is File => f instanceof File);
  if (texFiles.length === 0) {
    return Response.json(
      { error: "Attach the paper's LaTeX source (a .tex file, or a folder of them)" },
      { status: 422 },
    );
  }
  if (texFiles.length > MAX_TEX_FILES) {
    return Response.json({
      error: `At most ${MAX_TEX_FILES} .tex files are accepted`,
    }, { status: 422 });
  }
  const named: { relPath: string; file: File }[] = [];
  let total = 0;
  for (const file of texFiles) {
    const relPath = sanitizeTexPath(file.name);
    if (!relPath) {
      return Response.json({
        error: `${file.name} is not a usable .tex path`,
      }, { status: 422 });
    }
    if (file.size > MAX_TEX_FILE_BYTES) {
      return Response.json({
        error: `${relPath} is larger than ${MAX_TEX_FILE_BYTES / 1024 / 1024} MB`,
      }, { status: 422 });
    }
    total += file.size;
    named.push({ relPath, file });
  }
  if (total > MAX_TEX_TOTAL_BYTES) {
    return Response.json({
      error: `The LaTeX source is larger than ${
        MAX_TEX_TOTAL_BYTES / 1024 / 1024
      } MB in all`,
    }, { status: 422 });
  }

  const id = newRunId();
  const paths = paperPaths(id);
  const texDir = join(paths.inputs, "tex");
  try {
    Deno.mkdirSync(paths.inputs, { recursive: true, mode: 0o700 });
    for (const { relPath, file } of named) {
      const dest = join(texDir, relPath);
      Deno.mkdirSync(dirname(dest), { recursive: true, mode: 0o700 });
      Deno.writeFileSync(dest, new Uint8Array(await file.arrayBuffer()));
    }
    Deno.writeTextFileSync(
      join(paths.inputs, "rubric_branch.json"),
      JSON.stringify(rubric),
    );
  } catch (error) {
    return failed(error, 502);
  }
  const label = uploadLabel(
    fields["title"],
    folderLabel(named.map((n) => n.relPath)),
  );
  return start(label, scalars, {
    id,
    paperTex: texDir,
    rubric: join(paths.inputs, "rubric_branch.json"),
  });
}

export const handler = define.handlers({
  GET() {
    return Response.json({ runs: list() });
  },
  POST(ctx) {
    const contentType = ctx.req.headers.get("content-type") ?? "";
    if (!contentType.includes("multipart/form-data")) {
      return Response.json({
        error: "Attach the paper's LaTeX source and the rubric JSON as a multipart form",
      }, { status: 400 });
    }
    return postUpload(ctx.req);
  },
});
