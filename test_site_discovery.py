"""Declared website metadata is resolved without guessing dependency links."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from project_ops import ProjectOps

class SiteDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name).resolve()
        self.ops=ProjectOps(SimpleNamespace(ROOT=self.folder))
        self.project=dict(path=str(self.folder))
    def tearDown(self):self.temp.cleanup()
    def write(self,name,text):
        path=self.folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
    def test_canonical_is_used_instead_of_dependency_links(self):
        self.write('index.html','<link rel="stylesheet" href="https://fonts.example.com/style"><link href="https://smsheets.com/" rel="canonical"><meta property="og:url" content="https://smsheets.com/">')
        self.write('README.md','Docs: https://docs.example.com\nRepository: https://github.com/example/repo')
        result=self.ops.website(self.project)
        self.assertEqual(result['url'],'https://smsheets.com/');self.assertTrue(result['detected'])
        self.assertIn('index.html',result['urlSource'])
    def test_explicit_url_wins_and_invalid_explicit_is_not_silently_replaced(self):
        self.write('CNAME','smsheets.com')
        self.assertEqual(self.ops.website(dict(self.project,websiteUrl='https://chosen.example/'))['url'],'https://chosen.example/')
        result=self.ops.health(dict(self.project,websiteUrl='file:///etc/passwd'))
        self.assertEqual(result['state'],'unknown')
    def test_cname_package_and_labelled_readme_supported(self):
        for filename,text,expected in [('CNAME','smsheets.com\n','https://smsheets.com/'),('package.json','{"homepage":"https://app.example.com/"}','https://app.example.com/'),('README.md','Website: [Open site](https://live.example.com/)\nDocs: https://docs.example.com','https://live.example.com/')]:
            with self.subTest(filename=filename):
                self.write(filename,text);self.assertEqual(self.ops.website(self.project)['url'],expected);(self.folder/filename).unlink()
    def test_unrelated_links_and_ambiguous_canonicals_are_not_guessed(self):
        self.write('README.md','Documentation: https://docs.example.com\nGitHub: https://github.com/example/repo')
        self.assertEqual(self.ops.website(self.project)['url'],'')
        self.write('index.html','<link rel="canonical" href="https://one.example/"><link rel="canonical" href="https://two.example/">')
        result=self.ops.website(self.project);self.assertEqual(result['url'],'');self.assertIn('Multiple',result['detail'])
    def test_health_checks_detected_url_and_reports_it(self):
        self.write('index.html','<meta content="https://smsheets.com/" property="og:url">')
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(self.ops.opener,'open',return_value=Response()) as opened:
            result=self.ops.health(self.project)
        self.assertEqual(result['state'],'up');self.assertEqual(opened.call_args.args[0].full_url,'https://smsheets.com/')
        self.assertEqual(result['urlSource'],'index.html website metadata')
    def test_detected_url_persists_and_stale_check_cannot_replace_user_url(self):
        from work_control import WorkControl
        store=SimpleNamespace(save=lambda p:None)
        control=object.__new__(WorkControl);control.store=store
        p={};result=dict(detected=True,url='https://smsheets.com/',urlSource='index.html',state='up')
        control._save_health(p,result);self.assertEqual(p['websiteUrl'],'https://smsheets.com/')
        p['websiteUrl']='https://changed.example/'
        control._save_health(p,dict(result,state='down'))
        self.assertEqual(p['websiteUrl'],'https://changed.example/');self.assertEqual(p['websiteHealth']['state'],'up')

if __name__=='__main__':unittest.main()
