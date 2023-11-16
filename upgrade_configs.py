import sys
import pathlib
import yaml
from utils.config import Config


if len(sys.argv) < 2:
    print("Usage: python upgrade_configs.py <path to config file>", file=sys.stderr)
    print("This will parse the given config (if exists), add missing fields, and write it back.", file=sys.stderr)
    exit(1)

config_path = pathlib.Path(sys.argv[1])
if config_path.exists():
    with config_path.open("r") as f:
        config = Config.model_validate(yaml.safe_load(f), strict=True)
else:
    print("Config does not exist, creating a new one")
    config = Config()

with config_path.open("w") as f:
    yaml.safe_dump(config.model_dump(), f)
print("Config upgraded successfully!")
