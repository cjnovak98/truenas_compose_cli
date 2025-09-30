# TrueNAS App Deployer Script Documentation

## Overview
This Python script automates the deployment and management of applications on a TrueNAS system using its API. The application can either be deployed from compose files or catalog files, depending on user input.

## Installation
No explicit installation steps are required beyond ensuring you have Python 3 installed and all dependencies met (imported in the script).

## Usage

### Prerequisites
1. **TrueNAS Environment**: A TrueNAS system with Docker Application service configured.
2. **WSL Username/Password/API Key**: Necessary for authentication to access TrueNAS API.
3. **Python 3.x**: Ensure Python is installed and the `argparse`, `json`, `os`, `time`, `pathlib`, `yaml`, and `truenas_api_client` packages are available.

### Instructions

1. **Gather Compose or Catalog Files**:
    - Prepare a directory containing compose files (`.yaml`, `.yml`, `.json`) for custom applications.
    - Prepare a directory containing catalog files with application definitions from TUI, if applicable.

2. **Run the Script**:
    ```bash
    python3 <script_name>.py --host <TrueNAS_HOST> [--user <Username>] [--compose_dir <COMPOSE_DIR>] [--catalog_dir <CATALOG_DIR>] [--dry-run]
    ```

   - `--host`: The hostname or IP address of your TrueNAS instance.
   - `--user` (optional): Username to log in with. Defaults to "admin".
   - `--compose_dir`: Directory containing compose files.
   - `--catalog_dir`: Directory containing catalog files for application deployment.
   - `--dry-run` (optional): Show the actions that will be performed without making any changes.

### Example
```bash
python3 app_deployer.py --host 192.168.1.100 --compose_dir /path/to/compose/files --catalog_dir /path/to/catalog/files --dry-run
```

```bash
Please Enter your password:
[UPDATE] nginx -- Config has drifted. Updating....
[job 2960] RUNNING 0%
[job 2960] RUNNING 70% - Updating docker resources
[job 2960] SUCCESS 100% - Update completed for 'nginx'
[job 2960] Finished.