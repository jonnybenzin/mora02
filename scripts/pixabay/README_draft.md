# Mora02 - Pixabay Batch Image Downloader  
A command-line tool that searches Pixabay for images using multiple search terms and automatically archives them. It is designed for batch processing of image downloads, with configurable output directories and metadata handling. Used when generating visual content for AI training, media curation, or automated asset collection.

## Quick Start  
To download images for the search terms "eiffel tower sunset" and "olympic tower munich", run:  
```bash
pixabay "eiffel tower sunset" "olympic tower munich"
```  
This will search Pixabay, download the best match for each query, and save them in a timestamped directory under `/opt/mora02/output/_default/pixabay`.

## What It Does  
The script performs the following tasks:  
- Accepts multiple search terms as command-line arguments.  
- Uses the Pixabay API to search for images based on each query.  
- Downloads the best match (based on popularity) for each query.  
- Saves images in a timestamped directory under the `BASE_DIR` configuration.  
- Provides a summary of download statistics, including success and failure counts.  
- Uses a custom `User-Agent` header to avoid being blocked by Pixabay.  

## Parameters  
The script uses the following configuration parameters, which are defined in the source code:  

| Parameter         | Default Value                     | Description |
|------------------|-----------------------------------|-------------|
| `PIXABAY_API_KEY` | From environment variable         | Required API key for Pixabay. Must be set in the environment. |
| `BASE_DIR`        | `/opt/mora02/output/_default/pixabay` | Root directory where downloaded images are stored. |
| `IMAGE_TYPE`      | `"photo"`                         | Filters results to photos, illustrations, or vectors. |
| `ORIENTATION`     | `"horizontal"`                    | Filters results by image orientation. |

## Practical Examples  
### Example 1: Single Query  
```bash
pixabay "sunset over mountains"
```  
Useful for quickly fetching a single image for a specific concept.  

### Example 2: Multiple Queries in One Run  
```bash
pixabay "city skyline" "forest landscape" "modern architecture"
```  
Useful for batch processing of image assets for a project or dataset.  

### Example 3: Custom Output Directory  
Change `BASE_DIR` in the script to a custom path, such as `/opt/mora02/output/pixabay_custom`, to store images in a different location.  

## How It Works  
The script follows this pipeline:  
1. Accepts search terms from the command line.  
2. For each search term, it calls the Pixabay API with parameters like `image_type`, `orientation`, and `order`.  
3. Parses the JSON response to extract the best match (based on popularity).  
4. Downloads the image using a custom `User-Agent` to avoid being blocked.  
5. Saves the image in a timestamped directory under `BASE_DIR`.  
6. Outputs a summary of the download results, including success and failure counts.  

## Directory Structure  
```
/opt/mora02/output/_default/pixabay/
├── 202504151234_pixabay/
│   ├── 202504151234_123456.jpg
│   ├── 202504151234_789012.jpg
│   └── ...
└── 202504151235_pixabay/
    ├── 202504151235_345678.jpg
    └── ...
```  
- Each timestamped directory corresponds to a run of the script.  
- Images are saved with filenames that include the timestamp and Pixabay image ID.  

## Dependencies  
- **Python 3** (tested on Python 3.10)  
- **Standard libraries**: `os`, `sys`, `json`, `urllib.request`, `urllib.parse`, `datetime`, `pathlib`  
- **System tools**: `mkdir` (used via Python’s `Path.mkdir`)  

## Configuration  
To change the behavior of the script, modify the following variables in the source code:  

- **Line 14**: `PIXABAY_API_KEY` – must be set in the environment.  
- **Line 17**: `BASE_DIR` – change to a different output path if needed.  
- **Line 21**: `IMAGE_TYPE` – change to `"illustration"` or `"vector"` as needed.  
- **Line 24**: `ORIENTATION` – change to `"vertical"` or `"all"` for different image orientations.  

## Troubleshooting  
### 1. **No images found for a query**  
- **Cause**: The query may not match any images on Pixabay, or the API returned no results.  
- **Fix**: Try a different query or check the Pixabay API documentation for query constraints.  

### 2. **HTTP 401 or 403 error**  
- **Cause**: Invalid or missing `PIXABAY_API_KEY`.  
- **Fix**: Ensure the `PIXABAY_API_KEY` environment variable is set and valid.  

### 3. **Download fails with "Connection reset by peer"**  
- **Cause**: Pixabay may be blocking the request due to missing or outdated `User-Agent`.  
- **Fix**: Ensure the `User-Agent` header in the script is up to date and matches a real browser.  

### 4. **No output directory created**  
- **Cause**: The script may not have write permissions to the `BASE_DIR`.  
- **Fix**: Ensure the user running the script has write access to `/opt/mora02/output/_default/pixabay`.  

## Shell Script Collections  
### backup/  
- **backup_pixabay.sh**: Archives the latest Pixabay download directory to a backup location.  
- **backup_all.sh**: Archives all Pixabay download directories to a backup location.  
**Purpose**: Ensures that downloaded images are not lost in case of system failure or reconfiguration.  

### docker/  
- **build_pixabay.sh**: Builds a Docker image with the Pixabay downloader and its dependencies.  
- **run_pixabay.sh**: Runs the Pixabay downloader in a Docker container.  
**Purpose**: Enables containerized execution of the script for consistency and isolation.  

### system/  
- **install_deps.sh**: Installs system-level dependencies required by the script.  
- **setup_pixabay.sh**: Sets up the script environment, including creating output directories and configuring the API key.  
**Purpose**: Streamlines the setup and maintenance of the Pixabay downloader on the system.