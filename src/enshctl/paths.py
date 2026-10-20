"""Immutable path and value constants — no env-var dependency."""

from pathlib import Path

SAVE_DIR = Path("/data/saves")
LOG_DIR = Path("/data/logs")
MANIFESTS_DIR = Path("/data/manifests")
CONFIG_DIR = Path("/data/config")
MOUNT_POINT = Path("/data/gameserver")
BACKUP_BASE_DIR = Path("/data/backups")
WINE_PREFIX = Path("/data/wineprefix")
MODS_DIR = Path("/data/mods")
X11_DIR = Path("/tmp/.X11-unix")

GAME_EXE = MOUNT_POINT / "enshrouded_server.exe"
CONFIG_FILE = CONFIG_DIR / "enshrouded_server.json"
OUTPUT_CONFIG = CONFIG_DIR / "enshrouded_server.json"
GAME_CONFIG_EXAMPLE = MOUNT_POINT / "enshrouded_server_example.json"
PIDFILE = BACKUP_BASE_DIR / "enshctl.pid"
WINE_PREFIX_INIT_MARKER = WINE_PREFIX / ".wineboot-completed"
WINE_SERVER_BIN = Path("/usr/bin/wineserver")
DEPOT_KEYS_FILE = MANIFESTS_DIR / "depot.keys"
LATEST_MANIFEST_FILE = MANIFESTS_DIR / ".latest-manifest"
STATUS_FILE = ".installed"

RESTORE_TMP_DIR = SAVE_DIR.parent / "saves-restore-tmp"

APP_ID = "2278520"
DEPOT_ID = "2278521"
CONFIG_FILENAME = "enshrouded_server.json"
DEPOT_DOWNLOADER = ("/usr/bin/runuser", "-u", "steam", "--", "/opt/depotdownloader/DepotDownloader")
MANIFEST_TMP_DIR = "/tmp/depotdownloader"

BACKUP_DIR_LIVE = "live"
BACKUP_DIR_COLD = "cold"
BACKUP_DIR_EMERGENCY = "emergency"
BACKUP_DIRS = (BACKUP_DIR_LIVE, BACKUP_DIR_COLD, BACKUP_DIR_EMERGENCY)
