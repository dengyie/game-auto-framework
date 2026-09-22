"""
Tests for production deployment configurations and packaging artifacts.
Validates Dockerfile instructions, docker-compose YAML specs,
Systemd service units, Nginx configuration, and shell scripts.
"""

from pathlib import Path
import stat
import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent
DEPLOY_DIR = PROJECT_ROOT / "deploy"


def test_dockerfiles_structure():
    """Verify Dockerfiles contain essential production directives."""
    deploy_df = DEPLOY_DIR / "Dockerfile"
    root_df = PROJECT_ROOT / "Dockerfile"

    assert deploy_df.exists(), "deploy/Dockerfile must exist"
    assert root_df.exists(), "root Dockerfile must exist"

    for df_path in [deploy_df, root_df]:
        content = df_path.read_text(encoding="utf-8")
        assert "FROM python:3.12" in content
        assert "WORKDIR /app" in content
        assert "COPY pyproject.toml" in content
        assert "EXPOSE 8000" in content
        assert "HEALTHCHECK" in content
        assert "cluster/" in content
        assert "plugins/" in content


def test_docker_compose_files():
    """Verify docker-compose files are valid YAML and specify required services."""
    standard_compose = DEPLOY_DIR / "docker-compose.yml"
    redroid_compose = DEPLOY_DIR / "docker-compose.redroid.yml"

    assert standard_compose.exists()
    assert redroid_compose.exists()

    # 1. Standard compose
    with open(standard_compose, "r", encoding="utf-8") as f:
        std_data = yaml.safe_load(f)
    assert "services" in std_data
    assert "game-auto-framework" in std_data["services"]
    svc = std_data["services"]["game-auto-framework"]
    assert "8000:8000" in svc["ports"]
    assert svc["restart"] == "always"

    # 2. Redroid compose
    with open(redroid_compose, "r", encoding="utf-8") as f:
        red_data = yaml.safe_load(f)
    assert "services" in red_data
    assert "redroid-instance-01" in red_data["services"]
    assert "game-auto-framework" in red_data["services"]
    red_inst = red_data["services"]["redroid-instance-01"]
    assert red_inst["privileged"] is True
    assert "5555:5555" in red_inst["ports"]


def test_systemd_service_unit():
    """Verify systemd service file adheres to INI structure with required sections."""
    service_file = DEPLOY_DIR / "game-auto.service"
    assert service_file.exists()

    content = service_file.read_text(encoding="utf-8")
    assert "[Unit]" in content
    assert "[Service]" in content
    assert "[Install]" in content
    assert "Restart=always" in content
    assert "ExecStart=" in content
    assert "WantedBy=multi-user.target" in content


def test_nginx_configuration():
    """Verify Nginx reverse proxy configuration."""
    nginx_file = DEPLOY_DIR / "nginx.conf"
    assert nginx_file.exists()

    content = nginx_file.read_text(encoding="utf-8")
    assert "upstream game_auto_backend" in content
    assert "server 127.0.0.1:8000" in content
    assert "proxy_pass http://game_auto_backend" in content
    assert "gzip on;" in content
    assert "limit_req_zone" in content


def test_install_script_permissions():
    """Verify install.sh has execution permissions and includes target modes."""
    install_script = DEPLOY_DIR / "install.sh"
    assert install_script.exists()

    file_stat = install_script.stat()
    assert bool(file_stat.st_mode & stat.S_IXUSR), "install.sh must be executable"

    content = install_script.read_text(encoding="utf-8")
    assert "docker)" in content
    assert "redroid)" in content
    assert "systemd)" in content
