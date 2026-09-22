# web

The demonstration front end. Fresh 2 on Deno with Preact islands and `node:sqlite`.

```sh
deno install --frozen
deno task dev
```

<div align="center">

<img src="https://raw.githubusercontent.com/ITMO-NSS-Team/fedotmas/main/assets/web_home.png" alt="web" width="720"/>

</div>

| Variable                      | Default                        | What it is                                          |
| ----------------------------- | ------------------------------ | --------------------------------------------------- |
| `PORT`, `HOST`                | `8000`, `127.0.0.1`            | where `deno serve` listens (production)             |
| `FEDOTMAS_WEB_DATA_DIR`       | `./var`                        | run registry, fact stores, reports, uploaded inputs |
| `FEDOTMAS_ROOT`               | `..`                           | where `uv run` is spawned                           |
| `FEDOTMAS_PAPERBENCH_WORKDIR` | `~/.cache/fedotmas-paperbench` | PaperBench workdirs: workspaces, kept solution      |
| `FEDOTMAS_MODELS`             | two qwen ids                   | comma-separated model ids the Compose form offers   |
| `FEDOTMAS_RUNNER`             | unset                          | replaces `uv run ... run.py` (the e2e fake runner)  |
| `FEDOTMAS_WEB_TOKEN`          | unset                          | bearer token or `?token=` cookie for mutations      |
| `FEDOTMAS_MAX_RUNNING`        | `2`                            | runs allowed in flight at once (429 past it)        |
