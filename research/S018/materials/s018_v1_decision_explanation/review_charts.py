"""Review the exact phase-five HTML in embedded and standalone browser views."""
import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
from threading import Thread
from time import monotonic, sleep
from urllib.request import urlopen
from uuid import uuid4

import websocket

from strategy_manager import freeze_contracts as f

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
WORK = ROOT / '.tmp/s018-v1-stage5'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def wait(check):
    deadline = monotonic() + 15
    while monotonic() < deadline:
        result = check()
        if result:
            return result
        sleep(.10)
    raise TimeoutError('chart browser did not render')


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def samples():
    attempt = ROOT / read(WORK/'latest.json')['attempt']
    report = f.CandidateInspectionReport.from_dict(read(attempt/'report.json'))
    chart, = [case for case in report.pte_runtime.cases if case.case_id == 'pte-forward-chart']
    assert chart.status is f.InspectionStatus.PASS
    outcome = read(chart.evidence[0].resolve(ROOT))
    refs = {item.sha256: item for item in chart.evidence[1:]}
    scenarios = outcome['forward_chart']['scenarios']
    selected = {}
    for name in ('flat-wait-no-order', 'retained-real-window-1', 'retained-real-window-2'):
        artifact = refs[scenarios[name]['artifact_sha256']]
        html = artifact.resolve(ROOT).read_text(encoding='utf-8')
        context = json.loads(re.search(r'<script id="forward-context" type="application/json">(.*?)</script>',
                                       html, re.S)[1])
        original = next(case['facts'] for case in outcome['scenarios'] if case['case_id'] == name)
        rows = {row['decision_id']: row for row in original['decisions']}
        for event in context['execution']['decisions']:
            snapshot = event['explanation']
            summary = snapshot['basis'][0]['text']
            judgment = snapshot['judgment']
            date = event['signal_date']
            key = judgment
            if judgment == '目标清仓':
                key += '-到期' if '最长持有期' in summary else '-价格' if '退出线' in summary else '-余仓'
            if key in selected:
                continue
            row = rows[event['decision_id']]
            assert snapshot == row['payload']['strategy_output']['explanation']
            assert event['target_quantity'] == row['payload']['target_quantity']
            file = f'chart-{len(selected) + 1}.html'
            (WORK / file).write_text(html, encoding='utf-8')
            selected[key] = {'scenario': name, 'artifact': artifact.to_dict(), 'file': file,
                'decision_id': event['decision_id'], 'signal_date': date, 'valid_session': event['valid_session'],
                'state_reason': event['state_reason'], 'action': event['action'], 'target_quantity': event['target_quantity'],
                'snapshot': snapshot}
    expected = {'继续空仓 · 无需下单', '触发入场', '延续目标仓位', '提高目标仓位', '目标清仓-价格', '目标清仓-到期'}
    assert expected <= selected.keys(), selected.keys()
    wait_case = selected['继续空仓 · 无需下单']
    assert wait_case['scenario'] == 'flat-wait-no-order' and wait_case['state_reason'] == 'NO_ORDER'
    assert wait_case['target_quantity'] == 0 and wait_case['action'] == 'WAIT'
    return attempt, selected


def check_browser(selected):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(WORK)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    profile = WORK / ('chrome-' + uuid4().hex[:8])
    with (WORK/'chrome.log').open('wb') as log:
        chrome = subprocess.Popen([
            r'C:\Program Files\Google\Chrome\Application\chrome.exe', '--headless=new',
            '--no-first-run', '--disable-background-networking', '--remote-debugging-port=0',
            f'--user-data-dir={profile}', 'about:blank',
        ], stdout=log, stderr=log)
        try:
            port_file = profile/'DevToolsActivePort'
            port = wait(lambda: port_file.read_text().splitlines()[0] if port_file.exists() else None)
            with urlopen(f'http://127.0.0.1:{port}/json/list', timeout=5) as response:
                page = next(item for item in json.load(response) if item['type'] == 'page')
            ws = websocket.create_connection(page['webSocketDebuggerUrl'], suppress_origin=True, timeout=5)
            seq = 0

            def command(method, **params):
                nonlocal seq
                seq += 1
                ws.send(json.dumps({'id': seq, 'method': method, 'params': params}))
                while (result := json.loads(ws.recv())).get('id') != seq:
                    pass
                if 'error' in result:
                    raise RuntimeError(result['error'])
                return result['result']

            def evaluate(js):
                result = command('Runtime.evaluate', expression=js, returnByValue=True)
                if 'exceptionDetails' in result:
                    raise RuntimeError(result['exceptionDetails'])
                return result['result'].get('value')

            for index, (key, item) in enumerate(selected.items(), 1):
                snapshot = item['snapshot']
                relative = item['file'] + '#' + item['signal_date']
                wrapper = f'embedded-{index}.html'
                (WORK/wrapper).write_text(f"""<!doctype html><meta charset="utf-8">
<style>body{{margin:0;background:#0d1117}}iframe{{display:block;width:100%;height:890px;border:0}}</style>
<iframe src="{relative}"></iframe>""", encoding='utf-8')
                item['embedded'] = []
                for width in (1440, 390):
                    command('Emulation.setDeviceMetricsOverride', width=width, height=930,
                            deviceScaleFactor=1, mobile=False)
                    command('Page.navigate', url=base+'/'+wrapper)
                    displayed = wait(lambda: evaluate("""(() => {
                      const doc=document.querySelector('iframe')?.contentDocument;
                      const chart=doc?.querySelector('#pte-forward-chart');
                      const row=doc?.querySelector('.reading-basis .reading-row');
                      if (!chart?.dataset.selectedDate || !row) return null;
                      const head=doc.querySelector('.reading-head strong');
                      return {date:chart.dataset.selectedDate, judgment:head.textContent, summary:row.textContent,
                        fits:row.scrollHeight <= row.clientHeight + 1,
                        watch:doc.querySelector('.reading-next .reading-body').textContent,
                        event:doc.querySelector('.event-details').textContent};
                    })()"""))
                    assert displayed['date'] == item['signal_date'], (key, displayed)
                    assert displayed['judgment'] == snapshot['judgment'], (key, displayed)
                    assert displayed['summary'] == snapshot['basis'][0]['text'], (key, displayed)
                    assert displayed['watch'] == snapshot['next_watch'], (key, displayed)
                    assert displayed['fits'], (key, width, displayed)
                    assert item['valid_session'] in displayed['event'], (key, displayed)
                    item['embedded'].append({'width': width, **displayed})
                    if width == 1440 and index == 1:
                        png = command('Page.captureScreenshot', format='png')['data']
                        (WORK/'wait.png').write_bytes(base64.b64decode(png))
                command('Emulation.setDeviceMetricsOverride', width=1440, height=930, deviceScaleFactor=1, mobile=False)
                command('Page.navigate', url=base+'/'+relative)
                wait(lambda: evaluate("document.querySelector('.reading-head button')?.textContent"))
                evaluate("document.querySelector('.reading-head button').click()")
                detail = wait(lambda: evaluate("document.querySelector('.reading-detail')?.textContent"))
                assert detail == snapshot['explanation'], (key, detail)
                item['expanded_text'] = detail
                print(key, item['signal_date'], 'PASS', flush=True)
            ws.close()
        finally:
            chrome.terminate()
            chrome.wait(timeout=10)
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    attempt, selected = samples()
    check_browser(selected)
    (attempt.parent/'browser_review.json').write_text(
        json.dumps({'status': 'PASS', 'samples': selected}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
