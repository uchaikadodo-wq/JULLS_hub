"""Offline structural/security checks; does not replace docker compose config or runtime checks."""
from pathlib import Path
import json
import yaml
import jsonschema
root = Path(__file__).resolve().parent.parent
cfg = yaml.safe_load((root / "compose.local.yaml").read_text())
jsonschema.validate(cfg, json.loads((root / "local-dev/compose-spec.schema.json").read_text()))
assert cfg["networks"]["isolated"]["internal"] is True
assert cfg["services"]["web"]["ports"] == ["127.0.0.1:8080:8080"]
for name, service in cfg["services"].items():
    assert not service.get("privileged")
    assert service.get("network_mode") != "host"
    assert not service.get("extra_hosts")
    if name != "web":
        assert not service.get("ports")
    if name in ("app", "db", "node"):
        assert service["networks"] == ["isolated"]
    if name.endswith("-deps"):
        assert service["profiles"] == ["setup"]
    for volume in service.get("volumes", []):
        source = volume["source"] if isinstance(volume, dict) else volume.split(":")[0]
        assert source == "db" or source == "." or source.startswith("./local-dev/")
    if "image" in service and name not in ("app", "php-deps"):
        assert "@sha256:" in service["image"]
assert cfg["services"]["web"]["networks"] == ["ingress", "isolated"]
assert cfg["services"]["web"]["read_only"] is True
assert "env_file" not in cfg["services"]["web"]
assert "--ignore-scripts" in cfg["services"]["node-deps"]["command"]
assert "--no-scripts" in cfg["services"]["php-deps"]["command"]
assert "--no-plugins" in cfg["services"]["php-deps"]["command"]
print("PASS: Compose JSON schema and local security constraints (static only)")
