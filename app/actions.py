import subprocess
from pathlib import Path
import os
import yaml
from typing import Union, Sequence
import shlex

class main:
    def __init__(self, action_file: str = ""):
        try:
            with open(action_file, "r") as f:
                self.settings = yaml.safe_load(f)
        except FileNotFoundError as e:
            print("ERROR: Action YAML FILE NOT FOUND") 
            if action_file != "":
                raise

    def start(self):
        env = os.environ.copy()
        for action in self.settings:
            print(action)
            print(type(self.settings[action]))
            if type(self.settings[action]) != type(list()):
                raise Exception("action not a list")

            for command in self.settings[action]:
                if command == None:
                    continue

                command_start = command.split(" ")
                command_variables = " ".join(command_start[1:])
                command_start = command_start[0]

                if command_start == "ENV":
                    key = command_variables.split("=")[0]#.strip('"')
                    value = "=".join(command_variables.split("=")[1:])#.strip('"')
                    print(key, value)
                    env[key] = (value)
                    print(env)
                
                if command_start == "CLONE":
                    self.run(["git", "clone", command_variables], env=env)

                if command_start == "RUN":
                    self.run(command_variables, env=env)
                
                if command_start == "RETURN":
                    return command_variables
    
    def run(self, cmd: Union[str, Sequence[str]], *, env=None, cwd=None, add_env=None) -> subprocess.CompletedProcess:
        # If cmd is a string, split it into args safely (no shell required)
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)

        try:
            p = subprocess.run(
                list(cmd),
                env=env,
                cwd=cwd,
                text=True,            # gives you strings not bytes
                capture_output=True,
                check=True,
            )
            print("✅ RUN ok")
            if p.stdout:
                print("STDOUT:\n", p.stdout)
            if p.stderr:
                print("STDERR:\n", p.stderr)
            return p

        except Exception as e:
            print("❌ RUN failed")
            print("returncode:", e.returncode)
            print("cmd:", e.cmd)
            print("STDOUT:\n", e.stdout)
            print("STDERR:\n", e.stderr)
            raise

    def get_env(self):
        return os.environ.copy()