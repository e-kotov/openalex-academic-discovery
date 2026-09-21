#!/bin/bash
# Example: look up a researcher's profile, metrics, and recent outputs.
# Usage: profile_researcher.sh "<Full Name>" ["<institution keyword>"]
NAME="${1:?Usage: profile_researcher.sh \"<Full Name>\" [\"<institution keyword>\"]}"
python3 "$(dirname "$0")/../scripts/openalex_cli.py" author-profile \
  --name "$NAME" \
  ${2:+--institution "$2"}
