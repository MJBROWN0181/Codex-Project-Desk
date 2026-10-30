"""Fresh installs stay empty, even on a machine with a saved project index."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import server


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.patches=[patch.object(server,'DB',root/'tracker.sqlite3'),
                      patch.object(server,'EXPORT',root/'export.json'),
                      patch.object(server,'INDEX',root/'index.json')]
        for item in self.patches:item.start()
        server.EXPORT.write_text(json.dumps(dict(projects=[dict(projectId='private',label='Private project',projectKind='local')],threads=[])))

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def test_fresh_start_never_imports_available_private_index(self):
        with patch.object(server,'sync_codex') as imported:
            server.prepare_startup()
            imported.assert_not_called()
        self.assertEqual(server.load_projects(),[])
        self.assertTrue(server.setup_state()['required'])
        # Completing onboarding changes only the local flag, not project data.
        server.metadata('setupComplete',dict(at=server.now()))
        server.prepare_startup()
        self.assertFalse(server.setup_state()['required'])
        self.assertEqual(server.load_projects(),[])

    def test_existing_install_is_preserved_and_skips_wizard(self):
        server.initialize()
        p=server.new_project('Existing work');p['nextAction']='Keep this action';server.save(p)
        server.prepare_startup()
        self.assertFalse(server.setup_state()['required'])
        self.assertEqual(server.load_projects(),[p])

    def test_explicit_import_still_works(self):
        server.prepare_startup();server.sync_codex()
        self.assertEqual([p['id'] for p in server.load_projects()],['private'])


if __name__=='__main__':unittest.main()
