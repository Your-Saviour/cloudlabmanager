import yaml

class config:
    def __init__(self, settings_location="/data/settings.conf.yaml"):
        with open(settings_location, "r") as f:
            settings = yaml.safe_load(f)
        print(settings)