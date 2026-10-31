"""Isolated browser check; native worker is stubbed, no real chat is sent."""
import json,tempfile,threading,uuid
from pathlib import Path
from unittest.mock import patch
import server,project_folders
from desk_codex import DeskCodex
from playwright.sync_api import sync_playwright,expect

def run():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);server.DB=root/'test.sqlite3';server.DATA=root/'data';server.DATA.mkdir();server.initialize()
  server.metadata('setupComplete',{'at':server.now()})
  service=DeskCodex(server);service._send_worker=lambda receipt:None;server.CODEX_SERVICE=service
  real_scaffold=project_folders.scaffold
  http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
  worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
  try:
   with patch('project_folders.scaffold',side_effect=lambda p,**options:real_scaffold(p,root/'Projects',**options)):
    with sync_playwright() as pw:
     browser=pw.chromium.launch(headless=True);page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
     page.goto('http://127.0.0.1:'+str(http.server_port));page.wait_for_load_state('networkidle')
     page.get_by_role('button',name='+ Add project',exact=True).click()
     page.get_by_label('Project name',exact=True).fill('Browser Example')
     page.get_by_role('button',name='Save project',exact=True).click()
     page.get_by_role('button',name='Project folders',exact=True).click()
     dialog=page.get_by_role('dialog',name='Project folders')
     expect(dialog).to_contain_text(str(root/'Projects'/'Browser Example'))
     dialog.get_by_label('New feature name',exact=True).fill('Search')
     dialog.get_by_role('button',name='Add feature',exact=True).click()
     expect(dialog.get_by_label('Work folder',exact=True).locator('option')).to_have_count(2)
     dialog.get_by_label('Work folder',exact=True).select_option('Search')
     dialog.get_by_label('New idea for the selected folder',exact=True).fill('Add useful filters')
     dialog.get_by_role('button',name='Save idea',exact=True).click()
     expect(dialog.get_by_label('New idea for the selected folder',exact=True)).to_have_value('')
     ideas=list((root/'Projects'/'Browser Example'/'Features'/'Search'/'New Ideas').glob('*.md'))
     assert len(ideas)==1 and 'useful filters' in ideas[0].read_text()
     dialog.get_by_label('What should Codex work on?',exact=True).fill('Implement filters')
     dialog.get_by_role('button',name='Start new chat',exact=True).click()
     expect(dialog).not_to_be_visible()
     receipts=server.metadata('codexMessages');assert len(receipts)==1
     receipt=next(iter(receipts.values()));assert receipt['newFolderChat'] and receipt['recordsFeature']=='Search'
     assert receipt['cwd']==str(root/'Projects'/'Browser Example')
     assert receipt['recordsScope']==str(root/'Projects'/'Browser Example'/'Features'/'Search')
     assert receipt['title'].endswith(' Chat')
     assert not errors,errors
     browser.close();print('PASS: create project, scaffold, feature, idea, new dated-chat request, no JS errors; native transport stubbed.')
  finally:http.shutdown();http.server_close()

if __name__=='__main__':run()
