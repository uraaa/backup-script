#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
#  Backup-Script — Interactive Installer (Wizard)
#  Supported: Ubuntu 20.04 / 22.04 / 24.04
# ─────────────────────────────────────────────────────────────

# ── Colors and helpers ───────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

banner() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*"; }

ask() {
    # ask PROMPT DEFAULT  → stores the answer in the REPLY variable
    local prompt="$1"
    local default="${2:-}"
    if [[ -n "$default" ]]; then
        read -rp "$(echo -e "${BOLD}$prompt${NC} [${default}]: ")" REPLY
        REPLY="${REPLY:-$default}"
    else
        read -rp "$(echo -e "${BOLD}$prompt${NC}: ")" REPLY
    fi
}

choose() {
    # choose PROMPT opt1 opt2 ... → stores the number in CHOICE (1-based)
    local prompt="$1"; shift
    local options=("$@")
    echo -e "\n${BOLD}$prompt${NC}"
    local i=1
    for opt in "${options[@]}"; do
        echo -e "  ${CYAN}${i})${NC} $opt"
        ((i++))
    done
    while true; do
        read -rp "$(echo -e "${BOLD}Choose an option [1-${#options[@]}]:${NC} ")" CHOICE
        if [[ "$CHOICE" =~ ^[0-9]+$ ]] && (( CHOICE >= 1 && CHOICE <= ${#options[@]} )); then
            break
        fi
        err "Invalid choice. Please try again."
    done
}

confirm() {
    local prompt="$1"
    local reply
    read -rp "$(echo -e "${BOLD}$prompt (y/n)${NC} [y]: ")" reply
    reply="${reply:-y}"
    [[ "$reply" =~ ^[Yy] ]]
}

# ── Root check ───────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (sudo)."
    exit 1
fi

# ═════════════════════════════════════════════════════════════
#  STEP 0 — Welcome
# ═════════════════════════════════════════════════════════════
banner "Backup-Script — Installer v1.0"
echo "This wizard will help you:"
echo "  1. Install system dependencies"
echo "  2. Clone the repository"
echo "  3. Configure settings (DB, storage, notifications)"
echo "  4. Set up a cron job"
echo ""
if ! confirm "Continue with installation?"; then
    echo "Cancelled."; exit 0
fi

# ═════════════════════════════════════════════════════════════
#  STEP 1 — Installation directory
# ═════════════════════════════════════════════════════════════
banner "Step 1/8 — Installation Directory"

ask "Where to install backup-script?" "/opt/backup"
INSTALL_DIR="$REPLY"

if [[ -d "$INSTALL_DIR" ]]; then
    warn "Directory ${INSTALL_DIR} already exists."
    choose "What would you like to do?" \
        "Delete and reinstall" \
        "Update (git pull)" \
        "Use as is (skip cloning)" \
        "Cancel"
    DIR_ACTION=$CHOICE
    if [[ $DIR_ACTION -eq 4 ]]; then echo "Cancelled."; exit 0; fi
else
    DIR_ACTION=0  # need to clone
fi

# ═════════════════════════════════════════════════════════════
#  STEP 2 — System dependencies
# ═════════════════════════════════════════════════════════════
banner "Step 2/8 — System Dependencies"

info "Updating package list..."
apt-get update -qq

PACKAGES=(python3 python3-pip python3-venv git)

choose "Which database do you use for backups?" \
    "MySQL / MariaDB" \
    "PostgreSQL" \
    "None (files only, no DB dump)"
DB_TYPE=$CHOICE

case $DB_TYPE in
    1) PACKAGES+=(mysql-client)  ;;
    2) PACKAGES+=(postgresql-client) ;;
esac

info "Installing packages: ${PACKAGES[*]}"
apt-get install -y -qq "${PACKAGES[@]}"
info "System dependencies installed ✔"

# ═════════════════════════════════════════════════════════════
#  STEP 3 — Clone / update repository
# ═════════════════════════════════════════════════════════════
banner "Step 3/8 — Repository"

GIT_REPO_DEFAULT="https://github.com/uraaa/backup-script.git"
ask "Git repository URL" "$GIT_REPO_DEFAULT"
GIT_REPO="$REPLY"

case "${DIR_ACTION:-0}" in
    0)
        info "Cloning ${GIT_REPO} → ${INSTALL_DIR} ..."
        git clone "$GIT_REPO" "$INSTALL_DIR"
        ;;
    1)
        warn "Removing ${INSTALL_DIR} ..."
        rm -rf "$INSTALL_DIR"
        info "Cloning ${GIT_REPO} → ${INSTALL_DIR} ..."
        git clone "$GIT_REPO" "$INSTALL_DIR"
        ;;
    2)
        info "Updating repository (git pull) ..."
        cd "$INSTALL_DIR" && git pull
        ;;
    3)
        info "Using existing directory."
        ;;
esac

# ── Python venv & pip ────────────────────────────────────────
info "Creating Python virtual environment..."
python3 -m venv "${INSTALL_DIR}/venv"
source "${INSTALL_DIR}/venv/bin/activate"

info "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r "${INSTALL_DIR}/requirements.txt" -q
info "Python dependencies installed ✔"

# ═════════════════════════════════════════════════════════════
#  STEP 4 — Backup paths
# ═════════════════════════════════════════════════════════════
banner "Step 4/8 — Backup Paths"

BACKUP_PATHS=()
echo "Specify directories/files to back up (one at a time)."
echo "Enter an empty line when done."
echo ""
while true; do
    ask "Path (or Enter to finish)" ""
    [[ -z "$REPLY" ]] && break
    BACKUP_PATHS+=("$REPLY")
done

if [[ ${#BACKUP_PATHS[@]} -eq 0 ]]; then
    warn "No paths specified — the example from config.sample.yaml will be used"
    BACKUP_PATHS=("/var/www/myapp")
fi

ask "Exclude folders (comma-separated, e.g.: cache,tmp,vendor,node_modules)" "cache,tmp,vendor,node_modules"
IFS=',' read -ra EXCLUDES <<< "$REPLY"

# ═════════════════════════════════════════════════════════════
#  STEP 5 — Database configuration
# ═════════════════════════════════════════════════════════════
banner "Step 5/8 — Database"

DB_HOST="localhost"
DB_PORT="3306"
DB_NAME=""
DB_USER=""
DB_PASS=""

DB_DOCKER_CONTAINER=""

if [[ $DB_TYPE -ne 3 ]]; then
    case $DB_TYPE in
        1) DEFAULT_PORT=3306; DB_TYPE_NAME="mysql" ;;
        2) DEFAULT_PORT=5432; DB_TYPE_NAME="postgres" ;;
    esac

    if [[ $DB_TYPE -eq 2 ]] && confirm "Does PostgreSQL run inside a Docker container (dump via 'docker exec')?"; then
        ask "Docker container name running Postgres" "db"
        DB_DOCKER_CONTAINER="$REPLY"
    fi

    ask "DB host" "localhost"
    DB_HOST="$REPLY"

    ask "DB port" "$DEFAULT_PORT"
    DB_PORT="$REPLY"

    ask "Database name" "myapp"
    DB_NAME="$REPLY"

    ask "DB user" "myapp"
    DB_USER="$REPLY"

    ask "DB password" ""
    DB_PASS="$REPLY"

    info "DB configured: ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME} ✔"
else
    info "DB dump disabled."
fi

# ═════════════════════════════════════════════════════════════
#  STEP 6 — Storage
# ═════════════════════════════════════════════════════════════
banner "Step 6/8 — Backup Storage"

ask "Local backup directory" "/var/backups/myapp"
LOCAL_DIR="$REPLY"

ask "Temporary files directory" "/tmp/backup"
TEMP_DIR="$REPLY"

ask "How many archives to keep (rotation)" "14"
MAX_ARCHIVES="$REPLY"

# ── SharePoint ───────────────────────────────────────────────
SP_ENABLED=false
SP_TENANT="" SP_CLIENT="" SP_SECRET="" SP_SITE="" SP_DRIVE="" SP_FOLDER=""

if confirm "Enable SharePoint upload?"; then
    SP_ENABLED=true
    ask "Tenant ID" ""; SP_TENANT="$REPLY"
    ask "Client ID (App)" ""; SP_CLIENT="$REPLY"
    ask "Client Secret" ""; SP_SECRET="$REPLY"
    ask "Site ID" ""; SP_SITE="$REPLY"
    ask "Drive ID" ""; SP_DRIVE="$REPLY"
    ask "SharePoint folder" "/backups"; SP_FOLDER="$REPLY"
    info "SharePoint configured ✔"
fi

# ── Google Drive ─────────────────────────────────────────────
GD_ENABLED=false
GD_CREDS="" GD_FOLDER=""

if confirm "Enable Google Drive upload?"; then
    GD_ENABLED=true
    ask "Path to service_account.json file" "/opt/backup/service_account.json"
    GD_CREDS="$REPLY"
    ask "Google Drive Folder ID" ""
    GD_FOLDER="$REPLY"
    info "Google Drive configured ✔"
fi

# ── AWS S3 ───────────────────────────────────────────────────
S3_ENABLED=false
S3_KEY="" S3_SECRET="" S3_REGION="" S3_BUCKET="" S3_PREFIX="" S3_ENDPOINT=""

if confirm "Enable AWS S3 upload?"; then
    S3_ENABLED=true
    ask "AWS Access Key ID" ""; S3_KEY="$REPLY"
    ask "AWS Secret Access Key" ""; S3_SECRET="$REPLY"
    ask "AWS region" "us-east-1"; S3_REGION="$REPLY"
    ask "S3 bucket name" ""; S3_BUCKET="$REPLY"
    ask "Key prefix (folder inside bucket)" "backups"; S3_PREFIX="$REPLY"
    ask "Custom S3-compatible endpoint URL (leave empty for real AWS)" ""
    S3_ENDPOINT="$REPLY"
    info "AWS S3 configured ✔"
fi

# ── Mail.ru Cloud ────────────────────────────────────────────
MAILRU_ENABLED=false
MAILRU_USER="" MAILRU_PASS="" MAILRU_FOLDER=""

if confirm "Enable cloud.mail.ru upload?"; then
    MAILRU_ENABLED=true
    ask "Mail.ru email (login)" ""; MAILRU_USER="$REPLY"
    warn "Use an app password, not your regular one: Облако -> Настройки -> Пароли для внешних приложений"
    ask "App password" ""; MAILRU_PASS="$REPLY"
    ask "Remote folder" "/backups"; MAILRU_FOLDER="$REPLY"
    info "Mail.ru Cloud configured ✔"
fi

# ═════════════════════════════════════════════════════════════
#  STEP 7 — Email notifications
# ═════════════════════════════════════════════════════════════
banner "Step 7/8 — Notifications (Email / Telegram)"

ALERTS_ENABLED=false
SMTP_HOST="" SMTP_PORT="" SMTP_TLS="" SMTP_USER="" SMTP_PASS="" FROM_EMAIL="" TO_EMAILS=""

if confirm "Enable email error notifications?"; then
    ALERTS_ENABLED=true
    ask "SMTP host" "smtp.example.com"; SMTP_HOST="$REPLY"
    ask "SMTP port" "587"; SMTP_PORT="$REPLY"
    choose "Use TLS?" "Yes" "No"
    [[ $CHOICE -eq 1 ]] && SMTP_TLS=true || SMTP_TLS=false
    ask "SMTP username (login)" "noreply@example.com"; SMTP_USER="$REPLY"
    ask "SMTP password" ""; SMTP_PASS="$REPLY"
    ask "Sender email (from)" "$SMTP_USER"; FROM_EMAIL="$REPLY"
    ask "Recipient emails (comma-separated)" "admin@example.com"; TO_EMAILS="$REPLY"
    info "Email notifications configured ✔"
fi

# ── Telegram ─────────────────────────────────────────────────
TELEGRAM_ENABLED=false
TELEGRAM_TOKEN="" TELEGRAM_CHAT_ID=""

if confirm "Enable Telegram error notifications?"; then
    TELEGRAM_ENABLED=true
    ask "Bot token (from @BotFather)" ""; TELEGRAM_TOKEN="$REPLY"
    warn "Message your bot once (e.g. /start), then find your chat_id at:"
    warn "  https://api.telegram.org/bot<TOKEN>/getUpdates"
    ask "Chat ID" ""; TELEGRAM_CHAT_ID="$REPLY"
    info "Telegram notifications configured ✔"
fi

# ═════════════════════════════════════════════════════════════
#  Config generation
# ═════════════════════════════════════════════════════════════
banner "Generating Config"

CONFIG_FILE="${INSTALL_DIR}/config.yaml"

# ── paths section ──
{
cat <<EOF
paths:
EOF
for p in "${BACKUP_PATHS[@]}"; do
    # first path — with exclude, the rest — without
    if [[ "$p" == "${BACKUP_PATHS[0]}" && ${#EXCLUDES[@]} -gt 0 ]]; then
cat <<EOF
  - path: ${p}
    exclude:
EOF
        for ex in "${EXCLUDES[@]}"; do
            echo "      - ${ex}"
        done
    else
cat <<EOF
  - path: ${p}
EOF
    fi
done

# ── db section ──
if [[ $DB_TYPE -ne 3 ]]; then
cat <<EOF
db:
  type: ${DB_TYPE_NAME}
  host: ${DB_HOST}
  port: ${DB_PORT}
  name: ${DB_NAME}
  user: ${DB_USER}
  password: "${DB_PASS}"
EOF
    if [[ -n "$DB_DOCKER_CONTAINER" ]]; then
cat <<EOF
  docker_container: ${DB_DOCKER_CONTAINER}
EOF
    fi
fi

# ── backup section ──
cat <<EOF
backup:
  temp_dir: ${TEMP_DIR}
  local_dir: ${LOCAL_DIR}
  max_archives: ${MAX_ARCHIVES}
logging:
  dir: ${INSTALL_DIR}/logs
  max_log_files: 30
EOF

# ── alerts section (one sub-block per channel) ──
cat <<EOF
alerts:
  email:
    enabled: ${ALERTS_ENABLED}
EOF
if [[ "$ALERTS_ENABLED" == "true" ]]; then
cat <<EOF
    smtp_host: ${SMTP_HOST}
    smtp_port: ${SMTP_PORT}
    use_tls: ${SMTP_TLS}
    username: ${SMTP_USER}
    password: "${SMTP_PASS}"
    from_email: ${FROM_EMAIL}
    to_emails:
EOF
    IFS=',' read -ra EMAILS <<< "$TO_EMAILS"
    for em in "${EMAILS[@]}"; do
        echo "      - $(echo "$em" | xargs)"
    done
fi
cat <<EOF
  telegram:
    enabled: ${TELEGRAM_ENABLED}
EOF
if [[ "$TELEGRAM_ENABLED" == "true" ]]; then
cat <<EOF
    bot_token: "${TELEGRAM_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
EOF
fi

# ── sharepoint section ──
cat <<EOF
sharepoint:
  enabled: ${SP_ENABLED}
EOF
if [[ "$SP_ENABLED" == "true" ]]; then
cat <<EOF
  tenant_id: "${SP_TENANT}"
  client_id: "${SP_CLIENT}"
  client_secret: "${SP_SECRET}"
  site_id: "${SP_SITE}"
  drive_id: "${SP_DRIVE}"
  folder_path: "${SP_FOLDER}"
EOF
fi

# ── google_drive section ──
cat <<EOF
google_drive:
  enabled: ${GD_ENABLED}
EOF
if [[ "$GD_ENABLED" == "true" ]]; then
cat <<EOF
  credentials_file: ${GD_CREDS}
  folder_id: "${GD_FOLDER}"
EOF
fi

# ── aws_s3 section ──
cat <<EOF
aws_s3:
  enabled: ${S3_ENABLED}
EOF
if [[ "$S3_ENABLED" == "true" ]]; then
cat <<EOF
  access_key_id: "${S3_KEY}"
  secret_access_key: "${S3_SECRET}"
  region: "${S3_REGION}"
  bucket: "${S3_BUCKET}"
  prefix: "${S3_PREFIX}"
EOF
    if [[ -n "$S3_ENDPOINT" ]]; then
cat <<EOF
  endpoint_url: "${S3_ENDPOINT}"
EOF
    fi
fi

# ── mailru section ──
cat <<EOF
mailru:
  enabled: ${MAILRU_ENABLED}
EOF
if [[ "$MAILRU_ENABLED" == "true" ]]; then
cat <<EOF
  username: "${MAILRU_USER}"
  password: "${MAILRU_PASS}"
  remote_folder: "${MAILRU_FOLDER}"
EOF
fi

} > "$CONFIG_FILE"

info "Config saved: ${CONFIG_FILE}"

# Create required directories
mkdir -p "$LOCAL_DIR" "${INSTALL_DIR}/logs"

# ═════════════════════════════════════════════════════════════
#  STEP 8 — Cron
# ═════════════════════════════════════════════════════════════
banner "Step 8/8 — Schedule (cron)"

choose "How often should the backup run?" \
    "Every day at 3:00 AM" \
    "Every day at a custom time" \
    "Custom cron expression" \
    "Do not add to cron"

CRON_LINE=""
case $CHOICE in
    1) CRON_LINE="0 3 * * *" ;;
    2)
        ask "Hour (0-23)" "3"; CRON_HOUR="$REPLY"
        ask "Minute (0-59)" "0"; CRON_MIN="$REPLY"
        CRON_LINE="${CRON_MIN} ${CRON_HOUR} * * *"
        ;;
    3)
        ask "Enter cron expression (5 fields)" "0 3 * * *"
        CRON_LINE="$REPLY"
        ;;
    4)
        info "Cron not configured. You can add a cron job manually later."
        ;;
esac

if [[ -n "$CRON_LINE" ]]; then
    CRON_CMD="${CRON_LINE} ${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/backup.py --config ${CONFIG_FILE} >> /var/log/backup.log 2>&1"

    # Remove old entry if exists, add the new one
    ( crontab -l 2>/dev/null | grep -v "${INSTALL_DIR}/backup.py" || true; echo "$CRON_CMD" ) | crontab -

    info "Cron job added:"
    echo "  $CRON_CMD"
fi

# ═════════════════════════════════════════════════════════════
#  Summary
# ═════════════════════════════════════════════════════════════
banner "Installation Complete! 🎉"

echo -e "  ${BOLD}Directory:${NC}    ${INSTALL_DIR}"
echo -e "  ${BOLD}Config:${NC}       ${CONFIG_FILE}"
echo -e "  ${BOLD}Python venv:${NC}  ${INSTALL_DIR}/venv"
echo -e "  ${BOLD}Logs:${NC}         ${INSTALL_DIR}/logs"
echo -e "  ${BOLD}Backups:${NC}      ${LOCAL_DIR}"
echo ""
echo "To run manually:"
echo -e "  ${CYAN}sudo ${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/backup.py --config ${CONFIG_FILE}${NC}"
echo ""
echo "For a test run (dry-run):"
echo -e "  ${CYAN}sudo ${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/backup.py --config ${CONFIG_FILE} --dry-run --verbose${NC}"
echo ""
