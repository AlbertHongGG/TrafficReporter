from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from traffic_lpr_runtime.application.runtime_application import build_default_application
from traffic_lpr_runtime.domain.errors import RuntimeFailure


def main() -> int:
    runtime_script = Path(__file__).resolve()
    application = build_default_application(runtime_script)
    subcommand = sys.argv[1] if len(sys.argv) > 1 else 'status'

    try:
        raw_payload = sys.stdin.read().strip()
        payload = json.loads(raw_payload) if raw_payload else {}
        result = application.dispatch(subcommand, payload)
        sys.stdout.write(json.dumps(result))
        return 0
    except RuntimeFailure as error:
        detail = {
            'runtime': application.status() | {'detail': str(error)},
            'error': str(error),
        }
        sys.stderr.write(json.dumps(detail))
        return 1
    except Exception as error:
        failure: dict[str, Any] = {
            'runtime': application.status() | {'detail': 'Unexpected LPR runtime failure.'},
            'error': str(error),
            'traceback': traceback.format_exc(),
        }
        sys.stderr.write(json.dumps(failure))
        return 1
