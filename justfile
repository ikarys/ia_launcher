default: run

# Run in the foreground: http://0.0.0.0:8090 (reachable from the LAN)
run:
    ./run.sh

# Run the tests (installs the dev requirements in venv-launcher first)
test:
    [ -x venv-launcher/bin/python ] || uv venv -q --python 3.12 venv-launcher
    uv pip install -q --python venv-launcher/bin/python -r requirements-dev.txt
    venv-launcher/bin/python -m pytest -q

# Start the launcher at boot (systemd service)
install-service:
    sudo rm -f /etc/systemd/system/ia-launcher.service  # old install = symlink to the template
    sed "s|@USER@|$USER|; s|@DIR@|$PWD|" ia-launcher.service | sudo tee /etc/systemd/system/ia-launcher.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now ia-launcher

logs-service:
    journalctl -u ia-launcher -f

start:
    sudo systemctl start ia-launcher

stop:
    sudo systemctl stop ia-launcher

# After a code change (also stops the models it started)
restart:
    sudo systemctl restart ia-launcher
