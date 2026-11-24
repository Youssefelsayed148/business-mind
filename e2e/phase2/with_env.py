"""Load the per-run fake secrets into the environment, then exec the command."""
import json
import os
import sys

os.environ.update(json.load(open("/pki/env.json")))
os.execvp(sys.argv[1], sys.argv[1:])
