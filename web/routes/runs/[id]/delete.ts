import { remove } from "@/lib/runs.ts";
import { define } from "@/utils.ts";

export const handler = define.handlers({
  async POST(ctx) {
    await remove(ctx.params.id);
    return ctx.redirect("/runs", 303);
  },
});
