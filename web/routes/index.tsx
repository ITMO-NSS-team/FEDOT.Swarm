import { RunComposer } from "@/islands/RunComposer.tsx";
import { define } from "@/utils.ts";

export default define.page(() => (
  <main id="main-content" class="wrap" tabIndex={-1}>
    <div class="lede">
      <h1>Compose a swarm</h1>
      <p>
        A meta-agent writes the cast for a topic, a deterministic assembler
        checks it against the preset, and the swarm runs on a small model until
        it reaches the limit you set.
      </p>
    </div>
    <RunComposer />
  </main>
));
