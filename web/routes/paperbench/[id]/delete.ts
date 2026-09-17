import { remove } from "@/lib/paperbench.ts";
import { define } from "@/utils.ts";

export const handler = define.handlers({
  POST(ctx) {
    remove(ctx.params.id);
    return ctx.redirect("/runs", 303);
  },
});
