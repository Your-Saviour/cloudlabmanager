import yaml

class config:
    def __init__(self):
        self.settings = {}
        return None
    
    def add_settings(self, settings_location: str, setting_name: str):
        with open(settings_location, "r") as f:
            open_settings = yaml.safe_load(f)
        self.settings[setting_name] = open_settings
        return self.settings