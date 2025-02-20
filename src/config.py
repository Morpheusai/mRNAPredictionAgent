import os
import json

def load_local_config():
    # default config
    conf = {}
    default_config_file = os.path.join(os.path.dirname(__file__), '../config/config.json')
    if os.path.exists(default_config_file):
        with open(default_config_file, 'r', encoding='utf-8') as f:
            conf = json.load(f)

    log_level = os.getenv("LOG_LEVEL")
    if log_level:
        conf["log_level"] = log_level

    print(f'conf --- {conf}')

    return conf

g_config = load_local_config()