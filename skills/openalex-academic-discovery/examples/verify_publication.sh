#!/bin/bash
# Example: verify a publication's metadata and author team by DOI.
# Usage: verify_publication.sh [DOI]   (defaults to a well-known, highly cited paper)
DOI="${1:-10.1038/nature14539}"
python3 "$(dirname "$0")/../scripts/openalex_cli.py" verify-work --doi "$DOI"
