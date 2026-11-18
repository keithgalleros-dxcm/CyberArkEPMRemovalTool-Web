#!/bin/sh
# Open in Terminal: sh Install-connector.sh. No manual extraction or file copying.
set -eu
umask 077
find_python() {
    for name in python3.15 python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$name" >/dev/null 2>&1 && "$name" -I -c 'import sys; sys.exit(sys.version_info < (3,11))' >/dev/null 2>&1; then
            command -v "$name"; return 0
        fi
    done
    return 1
}
system=$(uname -s)
if [ "$system" = Darwin ]; then
    base="$HOME/Library/Application Support/Dexcom/EPMConnector"
else
    base="${XDG_DATA_HOME:-$HOME/.local/share}/dexcom/epm-connector"
fi
mkdir -p "$base"
target=$(mktemp -d "$base/installation.XXXXXXXX")
chmod 700 "$target"
python=$(find_python || true)
if [ -z "$python" ]; then
    echo 'Python 3.11+ not found. Setup needs to install Python; local administrator/sudo approval may be requested.'
    if [ "$system" = Darwin ]; then
        command -v curl >/dev/null || { echo 'curl is required. Ask IT to install Python 3.11+.'; exit 1; }
        curl --fail --location --proto '=https' --tlsv1.2 'https://www.python.org/ftp/python/3.15.2/python-3.15.2-macos11.pkg' -o "$target/python.pkg"
        echo '2c6104475535b720b45774c68b0dfc9fcca2235353cf9ff81e05488f89845396  '"$target/python.pkg" | shasum -a 256 -c -
        sudo /usr/sbin/installer -pkg "$target/python.pkg" -target /
        rm "$target/python.pkg"
        PATH="/Library/Frameworks/Python.framework/Versions/3.15/bin:$PATH"; export PATH
    elif [ "$system" = Linux ]; then
        if [ "$(id -u)" -eq 0 ]; then sudo_cmd=''; else sudo_cmd='sudo'; command -v sudo >/dev/null || { echo 'Ask IT to install Python 3.11+. sudo is unavailable.'; exit 1; }; fi
        if command -v apt-get >/dev/null; then
            $sudo_cmd apt-get update
            package=''
            for candidate in python3.15 python3.14 python3.13 python3.12 python3.11; do
                if apt-cache show "$candidate" >/dev/null 2>&1; then package=$candidate; break; fi
            done
            [ -n "$package" ] || { echo 'These OS repositories do not provide Python 3.11+. Ask IT for a supported runtime.'; exit 1; }
            $sudo_cmd apt-get install -y "$package"
        elif command -v dnf >/dev/null; then
            $sudo_cmd dnf install -y python3.13 || $sudo_cmd dnf install -y python3.12 || $sudo_cmd dnf install -y python3.11 || $sudo_cmd dnf install -y python3
        elif command -v zypper >/dev/null; then
            $sudo_cmd zypper --non-interactive install python313 || $sudo_cmd zypper --non-interactive install python312 || $sudo_cmd zypper --non-interactive install python311
        elif command -v pacman >/dev/null; then
            $sudo_cmd pacman -S --needed --noconfirm python
        elif command -v apk >/dev/null; then
            $sudo_cmd apk add python3
        else
            echo 'Unsupported package manager. Ask IT to install Python 3.11+, then open a fresh connector installer.'; exit 1
        fi
    else
        echo 'Unsupported OS. Use Windows, macOS or Linux.'; exit 1
    fi
    python=$(find_python || true)
    [ -n "$python" ] || { echo 'Python 3.11+ is still unavailable. Ask IT to configure a supported runtime.'; exit 1; }
    runtime_mode='installed-python'
else
    echo 'Compatible Python detected.'
    runtime_mode='existing-python'
fi
"$python" - "$target" "$runtime_mode" <<'CONNECTOR_PAYLOAD'
import base64,io,json,sys,zipfile
from pathlib import Path
root=Path(sys.argv[1])
with zipfile.ZipFile(io.BytesIO(base64.b64decode('__PAYLOAD__'))) as archive:
    archive.extractall(root)
for file in root.iterdir(): file.chmod(0o600)
(root/'setup-info.json').write_text(json.dumps({'runtime':sys.argv[2],'python':sys.executable}))
import shlex
(root/'Reconnect.command').write_text('#!/bin/sh\ncd -- '+shlex.quote(str(root))+' || exit 1\nexec '+shlex.join([sys.executable,str(root/'endpoint_connector.py'),'--config',str(root/'connector.private.json')])+'\n')
(root/'Reconnect.command').chmod(0o700)
CONNECTOR_PAYLOAD
"$python" -c 'import sys; sys.path.insert(0,sys.argv[1]); import endpoint_connector' "$target"
nohup "$python" -u "$target/endpoint_connector.py" --config "$target/connector.private.json" >"$target/connector.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$target/connector.pid"
sleep 3
kill -0 "$pid" 2>/dev/null || { echo "Connector stopped. Read $target/connector.log. Enrollment may have expired; use Install connector again."; exit 1; }
echo "Connector installed and started. Return to the portal. Files and logs: $target"
echo 'Use Reconnect.command in this folder to reconnect. A portal restart requires a fresh installer.'
