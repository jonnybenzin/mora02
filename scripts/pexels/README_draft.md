# Pexels Batch Image Downloader — Multi-Select Optional

A command-line tool for downloading images from Pexels API, with configurable number of results per query. Used for batch image retrieval with optional multi-select support. Designed for developers needing consistent, high-quality images for AI training or creative projects.

## Quick Start

```bash
pexels "sunset" "mountains"
```

This downloads one image per query. To download multiple versions per query:

```bash
pexels "sunset" --count 3
```

## What It Does

The script connects to the Pexels API to search for images based on text queries. It downloads images with landscape orientation by default, and stores them in a structured directory. It supports downloading multiple versions of images per query, which is useful for selecting the best image from several options.

## Parameters

The script uses the following configuration values, which are defined in the code:

| Parameter         | Default Value                          | Description |
|------------------|----------------------------------------|-------------|
| `PEXELS_API_KEY` | From environment variable              | Required API key for Pexels |
| `BASE_DIR`       | `/opt/mora02/output/_default/pexels`   | Root directory for image storage |
| `ORIENTATION`    | `landscape`                            | Image orientation filter |
| `USER_AGENT`     | `Mozilla/5.0 ...`                      | HTTP User-Agent header |
| `count`          | `1` (default)                          | Number of images to download per query |

## Practical Examples

### Example 1: Single image per query
```bash
pexels "eiffel tower"
```
Useful for projects requiring one representative image per query.

### Example 2: Multiple images per query
```bash
pexels "eiffel tower" --count 5
```
Useful for selecting the best image from several options, such as for AI training.

### Example 3: Multiple queries with multiple images
```bash
pexels "paris" "tokyo" --count 3
```
Useful for batch image retrieval with multiple options per query.

## How It Works

1. **Argument Parsing**: The script parses command-line arguments to extract search queries and the number of images to download per query.
2. **Directory Setup**: Creates a timestamped directory for storing images, with a `_multi` suffix if multiple images are requested.
3. **Pexels API Request**: Sends a request to the Pexels API with the query and number of results.
4. **Image Download**: Downloads each image to a subdirectory, named based on the query and count.
5. **Output Summary**: Displays a summary of how many images were successfully downloaded and how many failed.

## Directory Structure

```
/opt/mora02/output/_default/pexels/
├── 202404051200_pexels/
│   ├── paris/
│   │   ├── 01_123456.jpg
│   │   └── 02_789012.jpg
│   └── tokyo/
│       ├── 01_345678.jpg
│       └── 02_901234.jpg
└── 202404051200_pexels_multi_3/
    ├── sunset/
    │   ├── 01_123456.jpg
    │   ├── 02_789012.jpg
    │   └── 03_345678.jpg
```

- `202404051200_pexels/`: Directory for single-image downloads.
- `202404051200_pexels_multi_3/`: Directory for multi-image downloads (3 images per query).
- Subdirectories are named after the query, with spaces replaced by underscores.

## Dependencies

- **Python 3**
- **urllib.request**
- **json**
- **datetime**
- **os**
- **sys**
- **pathlib**

Ensure the `PEXELS_API_KEY` is set in the environment before running the script.

## Configuration

- **`PEXELS_API_KEY`**: Set in the code as `os.environ.get("PEXELS_API_KEY", "")`. Change this to your actual Pexels API key.
- **`BASE_DIR`**: Defined as `/opt/mora02/output/_default/pexels`. Modify this path if you want to store images elsewhere.
- **`ORIENTATION`**: Set to `landscape` by default. Change this to `portrait` or `square` if needed.

## Troubleshooting

### 1. **No images found**
- **Cause**: The query may not match any images on Pexels.
- **Fix**: Try a different query or increase the number of results per query.

### 2. **HTTP Error 401**
- **Cause**: Invalid or missing Pexels API key.
- **Fix**: Ensure `PEXELS_API_KEY` is set in the environment.

### 3. **Download fails**
- **Cause**: The image URL may be invalid or the server is unreachable.
- **Fix**: Retry the download or check the network connection.

### 4. **Too many images requested**
- **Cause**: The `--count` parameter exceeds the Pexels API limit (80).
- **Fix**: Use a value between 1 and 80 for `--count`.

---

## Shell Script Collections

### backup/
- `backup_pexels.sh`: Creates a tarball of the Pexels output directory for backup purposes.

### docker/
- `build_docker.sh`: Builds a Docker image containing the script and its dependencies.
- `run_docker.sh`: Runs the script inside a Docker container.

### system/
- `install_deps.sh`: Installs system-level dependencies required by the script.
- `setup_env.sh`: Sets up the environment, including the Pexels API key and directory structure.