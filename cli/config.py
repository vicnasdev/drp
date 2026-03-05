
from platformdirs import user_config_dir
import json, pathlib
import platform
import keyring


CONFIG_PATH = pathlib.Path(user_config_dir("drp")) / "config.json"

def get(key: str) -> str:
    if not CONFIG_PATH.exists():
        return None
    return json.loads(CONFIG_PATH.read_text()).get(key)

def set(key: str, value):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    data[key] = value
    CONFIG_PATH.write_text(json.dumps(data, indent=2))
    

def machine_info() -> dict:
    return {
        "os": platform.system(),
        "hostname": platform.node(),
    }
    
def set_secret(name: str, value: str):
    keyring.set_password("drp", name, value)
    
def get_secret(name: str) -> str:
    keyring.get_password("drp", name)

def del_secret(name: str):
    keyring.delete_password("drp", name)