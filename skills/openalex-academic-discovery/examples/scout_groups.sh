#!/bin/bash
# Example: scout research groups at the intersection of a method and a domain.
# Usage: scout_groups.sh ['<query>'] [COUNTRY,CODES]
QUERY="${1:-\"machine learning\" (\"protein folding\" OR \"drug discovery\")}"
COUNTRIES="${2:-US,CA,JP}"
python3 "$(dirname "$0")/../scripts/openalex_cli.py" find-groups \
  --query "$QUERY" \
  --countries "$COUNTRIES" \
  --from-year 2022 \
  --sample-size 100 \
  --top-n 5
