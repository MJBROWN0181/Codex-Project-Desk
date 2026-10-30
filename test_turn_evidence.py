import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock,patch
import turn_evidence as evidence


class TurnEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'session.jsonl'
        self.patch=patch.object(evidence,'SESSION_ROOT',self.root);self.patch.start()
        evidence._cache.clear()
        self.client=MagicMock()
        self.client.read_thread.return_value=dict(path=str(self.path))
        self.client.call.return_value=dict(data=[dict(id='turn',status='interrupted',completedAt=None)])
        self.row('session_meta',dict(id='chat'))
        self.row('event_msg',dict(type='task_started',turn_id='turn'))

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def row(self,kind,body):
        from datetime import datetime,timezone
        with self.path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(type=kind,payload=body,timestamp=datetime.now(timezone.utc).isoformat()))+'\n')

    def status(self):return evidence.monitor_turns(self.client,dict(threadId='chat'))['data'][0]['status']

    def test_open_desktop_turn_is_not_interrupted(self):
        self.assertEqual(self.status(),'inProgress')
        self.assertEqual(self.client.call.return_value['data'][0]['status'],'interrupted')

    def test_terminal_evidence_overrides_synthetic_status_after_append(self):
        self.assertEqual(self.status(),'inProgress')
        self.row('event_msg',dict(type='task_complete',turn_id='turn'))
        self.assertEqual(self.status(),'completed')

    def test_explicit_abort_is_still_interrupted(self):
        self.row('event_msg',dict(type='turn_aborted',turn_id='turn'))
        self.assertEqual(self.status(),'interrupted')

    def test_missing_wrong_or_stale_evidence_holds_without_false_failure(self):
        with patch.object(evidence.time,'time',return_value=time.time()+600):self.assertEqual(self.status(),'monitorUnknown')
        self.client.read_thread.return_value=dict(path=str(self.root/'missing'))
        self.assertEqual(self.status(),'monitorUnknown')
        self.client.read_thread.return_value=dict(path=str(self.path))
        self.assertEqual(evidence.monitor_turns(self.client,dict(threadId='different'))['data'][0]['status'],'monitorUnknown')

    def test_partial_appended_record_waits_for_newline(self):
        self.assertEqual(self.status(),'inProgress')
        with self.path.open('ab') as stream:stream.write(b'{"type":"event_msg","payload":{"type":"turn_aborted","turn_id":"turn"}}')
        self.assertEqual(self.status(),'inProgress')
        with self.path.open('ab') as stream:stream.write(b'\n')
        self.assertEqual(self.status(),'interrupted')
