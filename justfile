default: run

# Demarre l'IA Launcher : http://0.0.0.0:8090 (joignable depuis le LAN)
run:
    ./run.sh

# Tests (pytest, dans venv-launcher : uv pip install -r requirements-dev.txt)
test:
    venv-launcher/bin/python -m pytest -q

# Lance le launcher au boot de la WSL (service systemd)
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

# Apres une modif du code (arrete aussi les modeles lances)
restart:
    sudo systemctl restart ia-launcher
