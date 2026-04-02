import os
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
DEBATE_CHANNEL_ID = os.environ["DEBATE_CHANNEL_ID"]
CODING_CHANNEL_ID = os.environ["CODING_CHANNEL_ID"]
MAX_DEBATE_ROUNDS = int(os.environ.get("MAX_DEBATE_ROUNDS", "10"))
CONSENSUS_EARLY_ROUNDS = int(os.environ.get("CONSENSUS_EARLY_ROUNDS", "5"))
CLI_TIMEOUT = 120
