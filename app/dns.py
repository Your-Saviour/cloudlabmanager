from cloudflare import Cloudflare
import os

class main:
    def __init__(self):
        self.client = Cloudflare(
            api_token=os.environ.get("CLOUDFLARE_API_TOKEN"),  # This is the default and can be omitted
        )

    def get_all_zones(self):
        page = self.client.zones.list()
        cf_ids = {}
        for result in page.result:
            print(result)
            cf_ids[result.name] = result.id
        return cf_ids
    
    def get_zone_information(self, zone_id):
        zone = self.client.zones.get(
            zone_id=zone_id,
        )
        return zone.result