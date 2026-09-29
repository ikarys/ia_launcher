default: run

# Run in the foreground: http://0.0.0.0:8090 (reachable from the LAN)
run:
    ./run.sh

# Run the tests (installs the dev requirements in venv-hominfer first)
test:
    rm -rf venv-launcher  # pre-rename venv
    [ -x venv-hominfer/bin/python ] || uv venv -q --python 3.12 venv-hominfer
    uv pip install -q --python venv-hominfer/bin/python -r requirements-dev.txt
    venv-hominfer/bin/python -m pytest -q

# Start the launcher at boot (systemd service)
install-service:
    sudo rm -f /etc/systemd/system/hominfer.service  # old install = symlink to the template
    sed "s|@USER@|$USER|; s|@DIR@|$PWD|" hominfer.service | sudo tee /etc/systemd/system/hominfer.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl disable --now ia-launcher 2>/dev/null || true  # pre-rename unit
    sudo systemctl enable --now hominfer

logs-service:
    journalctl -u hominfer -f

start:
    sudo systemctl start hominfer

stop:
    sudo systemctl stop hominfer

# After a code change (also stops the models it started)
restart:
    sudo systemctl restart hominfer
