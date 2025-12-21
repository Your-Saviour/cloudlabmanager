from config import config
from actions import actions as actions_class


async def main():
    print("I DID A THING")
    actions = actions_class("/data/startup_action.conf.yaml")
    actions.start()
    return True

