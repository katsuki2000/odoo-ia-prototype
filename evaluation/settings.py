"""Settings read by the benchmarks and manual checks only; the backend never imports them."""

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env')

ODOO_BENCH_PASSWORD = os.getenv('ODOO_BENCH_PASSWORD', '')
ERP_MODEL_EVAL_TIMEOUT_SECONDS = 180
ERP_BENCHMARK_MAX_ROWS = 50
ERP_BENCHMARK_CAPTURE_PATH = _ROOT / 'captures' / 'erp_benchmark_eval.jsonl'
