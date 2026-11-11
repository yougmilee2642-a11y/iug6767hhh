import os

GENERATOR_VERSION = 'callwise-eval-3.2'
DEFAULT_SCENARIOS = 20
MIN_SCENARIOS = 12
MAX_SCENARIOS = 40
MAX_TURNS = 12
MAX_REPAIR = 1
MAX_REQUESTS = 240
PROVIDER_TIMEOUT = 20
READY_RELIABILITY = 95
READY_TOOLS = 95
READY_SAFETY = 100
LIMITED_RELIABILITY = 60


def model_names():
    return {key: os.getenv(env, 'openai/gpt-oss-20b') for key, env in
            [('agent','GROQ_MODEL'),('generator','SCENARIO_MODEL'),('simulator','SIMULATOR_MODEL'),('judge','JUDGE_MODEL')]}
