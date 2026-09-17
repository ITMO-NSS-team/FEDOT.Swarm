import { RunComposer } from "@/islands/RunComposer.tsx";
import { define } from "@/utils.ts";

export default define.page(() => (
  <main id="main-content" class="wrap" tabIndex={-1}>
    <div class="lede">
      <h1>Compose a swarm</h1>
      <p>
        A meta-agent writes the cast, a deterministic assembler checks it
        against the preset, and the swarm runs until it reaches the limit you
        set — against a topic you write, or against one fixed PaperBench
        rubric branch.
      </p>
    </div>
    <RunComposer />
  </main>
));
