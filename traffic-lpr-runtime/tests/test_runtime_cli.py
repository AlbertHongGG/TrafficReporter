from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.entrypoints import cli
from traffic_lpr_runtime.protocol import build_runtime_request_envelope


class _FakeStdin:
    def __init__(self, raw_text: str) -> None:
        self.buffer = io.BytesIO(raw_text.encode('utf-8'))


class RuntimeCliServeTests(unittest.TestCase):
    def test_serve_keeps_progress_on_protocol_stdout_while_flushing_noise_to_stderr(self) -> None:
        request = build_runtime_request_envelope(
            'ai-evidence',
            {'sourcePath': 'demo.mp4', 'description': 'desc'},
            request_id='req-progress',
            protocol_version=cli.LPR_RUNTIME_PROTOCOL_VERSION,
        )
        protocol_stdout = io.StringIO()
        protocol_stderr = io.StringIO()

        def build_application(runtime_script: Path):
            del runtime_script
            print('startup-noise')

            class ApplicationStub:
                def dispatch(self, subcommand: str, payload: dict[str, object]) -> dict[str, object]:
                    print('dispatch-noise')
                    cli.emit_runtime_progress({
                        'progress': 0.5,
                        'stage': 'localize',
                        'detail': 'Selecting coarse interval with AI.',
                        'done': False,
                        'failed': False,
                        'stepIndex': 3,
                        'stepCount': 11,
                    })
                    return {
                        'subcommand': subcommand,
                        'payload': payload,
                    }

            return ApplicationStub()

        with (
            patch.object(cli, 'build_default_application', side_effect=build_application),
            patch.object(cli.sys, 'stdin', _FakeStdin(json.dumps(request) + '\n')),
            patch.object(cli.sys, 'stdout', protocol_stdout),
            patch.object(cli.sys, '__stdout__', protocol_stdout),
            patch.object(cli.sys, 'stderr', protocol_stderr),
        ):
            exit_code = cli.serve(Path('runtime.py'))

        self.assertEqual(exit_code, 0)

        protocol_lines = protocol_stdout.getvalue().strip().splitlines()
        self.assertEqual(len(protocol_lines), 3)

        initial_progress = json.loads(protocol_lines[0])
        workflow_progress = json.loads(protocol_lines[1])
        success_envelope = json.loads(protocol_lines[2])

        self.assertEqual(initial_progress['kind'], 'progress')
        self.assertEqual(initial_progress['requestId'], 'req-progress')
        self.assertEqual(initial_progress['progress']['detail'], 'Starting ai-evidence request.')

        self.assertEqual(workflow_progress['kind'], 'progress')
        self.assertEqual(workflow_progress['requestId'], 'req-progress')
        self.assertEqual(workflow_progress['progress']['requestId'], 'req-progress')
        self.assertEqual(workflow_progress['progress']['stepIndex'], 3)
        self.assertEqual(workflow_progress['progress']['detail'], 'Selecting coarse interval with AI.')

        self.assertTrue(success_envelope['ok'])
        self.assertEqual(success_envelope['requestId'], 'req-progress')
        self.assertEqual(success_envelope['result']['subcommand'], 'ai-evidence')
        self.assertEqual(success_envelope['result']['payload'], {'sourcePath': 'demo.mp4', 'description': 'desc'})

        stderr_output = protocol_stderr.getvalue()
        self.assertIn('startup-noise', stderr_output)
        self.assertIn('dispatch-noise', stderr_output)


if __name__ == '__main__':
    unittest.main()