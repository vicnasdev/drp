#!/bin/bash
trap '' INT
cd /home/vic/Desktop/Code/Github/drp

# Run tests
DB_URL= /home/vic/venv/bin/python -m pytest tests/unit/test_help_bot.py -x -q 2>&1
echo "TEST_RC=$?"

# Commit and push
git add -A
git diff --cached --stat
git commit -m "fix bot context: strip JS/CSS, drop README, expand embed docs, add bias

- strip <script> and <style> blocks before feeding templates to bot
  (use_cases.html was dumping 15K of JS animation code as context)
- remove README.md from context (deploy/env-var docs, zero user value)
- expand embed section with step-by-step how-to and iframe example
- add personality: bot now advocates for drp in comparisons
- context reduced from 30K to 15K chars (cleaner signal)"
git push
echo "PUSH_DONE"
rm -f /home/vic/Desktop/Code/Github/drp/_run.sh
