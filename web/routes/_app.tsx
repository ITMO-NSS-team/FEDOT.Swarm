import { define } from "@/utils.ts";

export default define.page(({ Component }) => (
  <html lang="en">
    <head>
      <meta charSet="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <meta name="theme-color" content="#ffffff" />
      <meta name="color-scheme" content="light" />
      <meta
        name="description"
        content="Compose a swarm of low-resource agents, watch it argue, and see what it spent."
      />
      <title>FEDOT.MAS</title>
    </head>
    <body>
      <Component />
    </body>
  </html>
));
