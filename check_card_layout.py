"""Content-height staggered cards, real temporary HTTP server; no live work."""
from pathlib import Path
import tempfile,threading
from playwright.sync_api import sync_playwright,expect
import server

PACKED="""() => {
 const cards=[...document.querySelectorAll('article.project')].map(n=>n.getBoundingClientRect());
 for(let i=0;i<cards.length;i++)for(let j=i+1;j<cards.length;j++){
  const a=cards[i],b=cards[j];if(a.left<b.right-1 && a.right>b.left+1 && a.top<b.bottom-1 && a.bottom>b.top+1)return false;
 }
 const columns=new Map();for(const r of cards){const x=Math.round(r.left);if(!columns.has(x))columns.set(x,[]);columns.get(x).push(r);}
 for(const column of columns.values()){
  column.sort((a,b)=>a.top-b.top);
  for(let i=1;i<column.length;i++){const gap=column[i].top-column[i-1].bottom;if(gap<17.5 || gap>22.5)return false;}
 }
 return true;
}"""
with tempfile.TemporaryDirectory() as folder:
    server.DB=Path(folder)/'layout.sqlite3';server.initialize()
    ids={}
    for name in ['A Long project','B Short project','C Short project','D Short project','E Short project','F Short project','G Short project','H Short project']:
        p=server.new_project(name);ids[name]=p['id']
        if name.startswith('A'):p['nextAction']='A detailed plan with real text.\n'*32
        if name.startswith('B'):server.event(p,server.now(),'Longer activity details to expand. '*70,'Manual','fixture-note')
        server.save(p)
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1360,'height':1000});errors=[];writes=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle');page.locator('#sort').select_option('name')
            page.wait_for_function(PACKED)
            def card(name):return page.locator('article[data-id="'+ids[name]+'"]')
            tall=card('A Long project').bounding_box();short=card('C Short project').bounding_box()
            assert tall['height']>short['height']+400,'Short card must not stretch to match a long neighbor'
            assert card('D Short project').bounding_box()['y']<tall['y']+tall['height']-100,'Next card must fill the space beneath a shorter neighbor'
            Path('output').mkdir(exist_ok=True);page.screenshot(path='output/card-layout-desktop.png',full_page=True)
            # Expanding details changes only content height; spans automatically
            # update without rebuilding the cards or closing the details.
            detail=card('B Short project').locator('.activity-note');before=card('B Short project').bounding_box()['height']
            detail.locator('summary').click();expect(detail).to_have_attribute('open','');page.wait_for_function(PACKED)
            assert card('B Short project').bounding_box()['height']>before+80
            detail.locator('summary').click();page.wait_for_function(PACKED)
            for width,columns in [(1000,2),(390,1),(1360,3)]:
                page.set_viewport_size({'width':width,'height':900});page.wait_for_function(PACKED)
                boxes=page.locator('article.project').evaluate_all('(cards)=>cards.map(c=>c.getBoundingClientRect().left)')
                assert len({round(x) for x in boxes})==columns,(width,boxes)
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            page.locator('#search').fill('C Short');expect(page.locator('article.project')).to_have_count(1);page.wait_for_function(PACKED)
            page.locator('#search').fill('No matching project');expect(page.locator('.no-results')).to_be_visible();expect(page.locator('article.project')).to_have_count(0)
            page.locator('#search').fill('');expect(page.locator('article.project')).to_have_count(8);page.wait_for_function(PACKED)
            # Pins still lead the existing DOM/keyboard order and visual placement.
            p=next(p for p in server.load_projects() if p['id']==ids['H Short project']);p['pinned']=True;server.save(p);page.evaluate('load()');page.wait_for_function(PACKED)
            expect(page.locator('article.project').first).to_have_attribute('data-id',p['id'])
            assert not errors,errors
            assert not writes,writes
            browser.close()
        print('PASS: natural card heights, shorter columns filled without gaps or overlap, expanding/collapsing details, one/two/three columns, filters/empty state, pinned order; no live work')
    finally:http.shutdown();http.server_close();worker.join()
