# Deploy

Start here to run the server. Host paths in the compose files are relative to this directory.

| File                     | Purpose                                                                               |
| ------------------------ | ------------------------------------------------------------------------------------- |
| `docker-compose.yml`     | Production sample. Adjust `enshrouded.env`, then `docker compose up -d`.              |
| `enshrouded.env`         | Sample settings consumed by the compose file.                                         |
| `docker-compose.dev.yml` | Local development only (builds the repo root). Run via `just dev` from the repo root. |

```bash
docker compose up -d
docker compose logs -f
```

## `enshrouded_server.json`

Sample Enshrouded Server configuration file.

You can inject it into the container by mounting it as `/data/config/enshrouded_server.json`.

> [!TIP]
> The recommended way to configure the server is to use only the environment variables.
>
> See [Environment Variable Config Reference](../docs/env-config-reference.md).
