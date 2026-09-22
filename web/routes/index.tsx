import { page } from "fresh";
import { RunComposer } from "@/islands/RunComposer.tsx";
import { models } from "@/lib/models.ts";
import { Head } from "fresh/runtime";
import { define } from "@/utils.ts";

/** `/?token=...` stores the API token as a cookie, so a shared demo link works when
 * `FEDOTMAS_WEB_TOKEN` is set; the page itself never shows it. */
export const handler = define.handlers({
  GET(ctx) {
    const url = new URL(ctx.req.url);
    const token = url.searchParams.get("token");
    if (token === null) return page();
    url.searchParams.delete("token");
    const headers = new Headers({ location: url.pathname + url.search });
    headers.append(
      "set-cookie",
      `fedotmas_token=${
        encodeURIComponent(token)
      }; Path=/; HttpOnly; SameSite=Strict`,
    );
    return new Response(null, { status: 303, headers });
  },
});

export default define.page(() => (
  <main id="main-content" class="wrap" tabIndex={-1}>
    <Head>
      <title>Compose · FEDOT.Swarm</title>
      <link rel="icon" type="image/svg+xml" href="/icon-compose.svg" />
    </Head>
    <div class="lede">
      <h1>Compose a swarm</h1>
      <p>
        A meta-agent writes the cast, a deterministic assembler checks it
        against the preset, and the swarm runs until it reaches the limit you
        set: against a topic you write, or against one PaperBench rubric branch
        with a coding agent per voice.
      </p>
    </div>
    <RunComposer models={models()} />
  </main>
));
