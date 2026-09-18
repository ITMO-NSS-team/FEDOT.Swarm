import { App, staticFiles } from "fresh";
import { dataDirectory, projectRoot } from "@/lib/paths.ts";

export const app = new App()
  .use(staticFiles())
  .fsRoutes();

if (import.meta.main) {
  const port = Number(Deno.env.get("PORT") ?? 8000);
  const hostname = Deno.env.get("HOST") ?? "127.0.0.1";
  console.log(
    `fedotmas web: project ${projectRoot()}, data ${dataDirectory()}, listening on ${hostname}:${port}`,
  );
  await app.listen({ port, hostname });
}
