from config import main as config_class
from actions import main as actions_class
from data import main as data_class


async def main():
    print("I DID A THING")
    actions = actions_class("/data/startup_action.conf.yaml")
    startup_config = actions.start()
    
    config = config_class()
    config.add_settings(startup_config, "startup")



    core_settings_file = "/app/" + config.settings["startup"]["core_settings"]
    config.add_settings(core_settings_file, "core")

    #data = data_class(config.settings["core"]["database_location"])
    #data.store_metadata("blah", "blah")

    print(config.settings)

    if "git_url" in config.settings["startup"]:
        if "git_key" in config.settings["startup"]:
            actions.run(["git", "clone", config.settings["startup"]["git_url"]], env = {"GIT_SSH_COMMAND": f"ssh -i {config.settings["startup"]["git_key"]} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"})
        else:
            raise  Exception("I DIDNT PROGRAM THIS")
        
    init_data(config)
    return True

def init_data(config):
    env = actions_class().get_env()
    print(env)

    data = data_class(config.settings["core"]["database_location"])
    data.store_metadata("HOST_HOSTNAME", env["HOST_HOSTNAME"])

