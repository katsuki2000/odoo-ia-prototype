#!/bin/bash
ROOT=/home/user/odoo-ia-prototype
PY=$ROOT/.venv/bin/python3
for pair in "base:$ROOT" "merge:$ROOT/.scratch/merge_check"; do
  name=${pair%%:*}; tree=${pair#*:}
  (cd $tree && timeout 1500 $PY -m pytest -q --no-header -p no:cacheprovider -n auto -m "not integration" --ignore=tests/oca_sample code_intelligence/tests tests 2>&1 | grep -E "^(FAILED|ERROR)|passed|failed" | sed 's/ - .*//' | sort > $ROOT/.scratch/res_$name.txt)
done
echo done > $ROOT/.scratch/res_done.txt
