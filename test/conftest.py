import json
import os


def get_resources_folder() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def get_config(name: str) -> dict:
    conf_file = os.path.join(get_resources_folder(), f"{name}.json")
    return json.load(open(conf_file))
