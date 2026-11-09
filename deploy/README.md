# Deploy

Start here to run the server. Host paths in the compose files are relative to this directory.

| File                     | Purpose                                                                                |
| ------------------------ | -------------------------------------------------------------------------------------- |
| `docker-compose.yml`     | Production sample. Copy `.env.example` to `.env`, adjust, then `docker compose up -d`. |
| `.env.example`           | Sample settings consumed by the compose file.                                          |
| `docker-compose.dev.yml` | Local development only (builds the repo root). Run via `just dev` from the repo root.  |

```bash
cp .env.example .env
docker compose up -d
docker compose logs -f
```
