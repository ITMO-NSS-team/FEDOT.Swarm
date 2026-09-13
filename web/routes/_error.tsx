import { HttpError } from "fresh";
import { Head } from "fresh/runtime";
import { define } from "@/utils.ts";

export default define.page(({ error }) => {
  const status = error instanceof HttpError ? error.status : 500;
  const title = status === 404 ? "Not found" : "Something went wrong";
  const detail = status === 404
    ? "That page or run does not exist."
    : "The request could not be completed.";
  return (
    <main id="main-content" class="wrap error-page" tabIndex={-1}>
      <Head>
        <title>{title} · FEDOT.MAS</title>
      </Head>
      <span class="error-code">{status}</span>
      <h1>{title}</h1>
      <p>{detail}</p>
      <a class="primary-button" href="/">Compose a swarm</a>
    </main>
  );
});
