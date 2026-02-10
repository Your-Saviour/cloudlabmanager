import json

class main:
    def __init__(self, location: str):
        self.location = location
    
    def store_metadata(self, key, value):
        print("INFO:", key, value)
        with open(self.location, 'r+', encoding='utf-8') as json_file:
            data = json.load(json_file)

        if key in data:
            print("WARN: KEY ALREADY EXISTS")

        data[key] = value
        print(data)
            
        with open(self.location, 'w+', encoding='utf-8') as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)

    def get_metadata(self, key):
        try:
            with open(self.location, 'r', encoding='utf-8') as json_file:
                data = json.load(json_file)
            return data.get(key)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def get_all(self):
        try:
            with open(self.location, 'r', encoding='utf-8') as json_file:
                return json.load(json_file)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def update_metadata(self, key, value):
        try:
            with open(self.location, 'r', encoding='utf-8') as json_file:
                data = json.load(json_file)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data[key] = value
        with open(self.location, 'w+', encoding='utf-8') as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)

    def delete_metadata(self, key):
        try:
            with open(self.location, 'r', encoding='utf-8') as json_file:
                data = json.load(json_file)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        data.pop(key, None)
        with open(self.location, 'w+', encoding='utf-8') as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)