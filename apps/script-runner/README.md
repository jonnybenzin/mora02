# Mora02 Script Runner

FastAPI service for gifer, clipper, typer scripts.
Fully portable Docker container.

## Quick Start

### 1. Build Image

```bash
cd /opt/mora02/docker/script-runner
chmod +x build.sh
./build.sh
```

### 2. Add to docker-compose.yml

Add the service from `docker-compose-snippet.yml` to your main compose file.

### 3. Create Data Directory

```bash
mkdir -p /opt/mora02/docs/scripts/{wip,final/gifer,final/clipper,final/typer}
```

### 4. Start Service

```bash
cd /opt/mora02/docker
docker compose up -d script-runner
```

## API Endpoints

Base URL: `http://mora02.local:8096`

### Session Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/session/create` | Create new session |
| POST | `/upload/{session_id}` | Upload files |
| GET | `/session/{session_id}/files` | List files |
| DELETE | `/session/{session_id}` | Delete session |

### Script Execution

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/run/gifer` | Create GIF from images |
| POST | `/run/typer` | Create text frame PNG |
| POST | `/run/clipper` | Create video clip |

### Output

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/preview/{session_id}/{filename}` | Preview output |
| POST | `/finalize` | Move to final directory |
| GET | `/final/{script_type}/{filename}` | Get finalized file |

## Example: Create GIF

### 1. Create Session

```bash
curl -X POST http://mora02.local:8096/session/create
```

Response:
```json
{
  "session_id": "2501241530_a3f2b1",
  "message": "Session created. Upload files to /upload/2501241530_a3f2b1"
}
```

### 2. Upload Images

```bash
curl -X POST http://mora02.local:8096/upload/2501241530_a3f2b1 \
  -F "files=@image1.png" \
  -F "files=@image2.png" \
  -F "files=@image3.png"
```

### 3. Create GIF

```bash
curl -X POST http://mora02.local:8096/run/gifer \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "2501241530_a3f2b1",
    "durations": "1, 2, 3",
    "quality": "high"
  }'
```

Response:
```json
{
  "success": true,
  "filename": "2501241530_gifer.gif",
  "preview_url": "/preview/2501241530_a3f2b1/2501241530_gifer.gif"
}
```

### 4. Finalize

```bash
curl -X POST http://mora02.local:8096/finalize \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "2501241530_a3f2b1",
    "filename": "2501241530_gifer.gif",
    "script_type": "gifer"
  }'
```

## Example: Create Text Frame (Typer)

No session needed for typer:

```bash
curl -X POST http://mora02.local:8096/run/typer \
  -H "Content-Type: application/json" \
  -d '{
    "text": "HELLO\\nWORLD",
    "size": "1080x1080",
    "template": "dark",
    "font": "bold",
    "fontsize": "large",
    "layout": "centered"
  }'
```

## Parameters

### Gifer

| Parameter | Default | Options |
|-----------|---------|---------|
| durations | "1" | Comma-separated seconds |
| quality | "medium" | low, medium, high, ultra |
| size | auto | "800x600" or "800" |

### Typer

| Parameter | Default | Options |
|-----------|---------|---------|
| size | "1080x1080" | WxH format |
| template | "dark" | dark, darker, light, black |
| font | "bold" | bold, bold-italic, thin, thin-italic |
| fontsize | "medium" | small, medium, large, or pixels |
| layout | "left" | left, centered |

### Clipper

| Parameter | Default | Options |
|-----------|---------|---------|
| resolution | "1080p" | 1080p, 720p, 4k, square, story |
| durations | "4" | Seconds per image |
| animation | "pan" | pan, zoom_in, zoom_out, none |
| direction | "90" | 0-360 degrees |
| intensity | "20" | 1-100 |
| transition | "1" | Seconds between clips |

## Directory Structure

```
/opt/mora02/docs/scripts/
├── wip/
│   └── {session_id}/
│       ├── input/    # Uploaded files
│       └── output/   # Generated files
└── final/
    ├── gifer/        # Finalized GIFs
    ├── clipper/      # Finalized videos
    └── typer/        # Finalized PNGs
```

## nginx-images Integration

Add to nginx config to serve script outputs:

```nginx
location /scripts/ {
    alias /opt/mora02/docs/scripts/;
    autoindex on;
}
```

Then access finalized files via:
`http://mora02.local:8092/scripts/final/gifer/filename.gif`

## Portability

Container includes:
- Python 3.11
- ffmpeg (for clipper)
- Pillow (for gifer, typer)
- JetBrains Mono fonts

No external dependencies. Copy container to any Docker host.
