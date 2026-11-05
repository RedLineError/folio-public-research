"""Public-data adapters for the installed Trader skills. No trading endpoints."""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
import edgar13f as edgar
import ptr

PUBLIC = ROOT / 'dist/research'
CACHE = ROOT / 'cache'
LOCK = threading.RLock()
CONFIG = Path(os.environ.get('FOLIO_SOURCE_CONFIG', str(ROOT.parent / 'trader/trader/config.json')))

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(path)

def cached(path, seconds):
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        try:
            fetched = dt.datetime.fromisoformat(data['fetched_at']).timestamp()
        except (KeyError, TypeError, ValueError):
            return None
        if 0 <= time.time() - fetched < seconds:
            return data

class CachedFetcher(edgar.Fetcher):
    def get(self, url, sec=True):
        path = CACHE / ('sec-' + hashlib.sha256(url.encode()).hexdigest())
        # Archive documents are immutable for this session; submissions refresh hourly.
        ttl = 86400 if '/Archives/' in url else 3600
        if path.exists() and time.time() - path.stat().st_mtime < ttl:
            return path.read_bytes()
        result = super().get(url, sec)
        CACHE.mkdir(exist_ok=True)
        path.write_bytes(result)
        return result

def catalog():
    return {'updated_at': now(), 'filers': [{'cik': f['cik'], 'name': f['name'], 'aliases': f.get('aliases', [])} for f in edgar.load_filers()]}

def investor(cik, refresh=False):
    if not re.fullmatch(r'\d{1,10}', str(cik)): raise ValueError('Enter a numeric SEC CIK with up to 10 digits.')
    cik = edgar.cik10(cik)
    path = PUBLIC / ('investor-' + cik + '.json')
    with LOCK:
        previous = cached(path, 900 if refresh else 3600)
        if previous: return previous
        ua = edgar.user_agent(config_path=str(CONFIG))
        if not ua: raise ValueError('Set SEC_USER_AGENT to your name and email before requesting SEC filings.')
        fetcher = CachedFetcher(ua=ua, pause=.25)
        meta, rows, filings = edgar.load_quarter(fetcher, cik)
        index = edgar.ticker_index(fetcher)
        overrides = edgar.load_overrides([str(ROOT / 'vendor/share_classes.json')])
        positions, total = edgar.build(meta, rows, index, overrides, combine=True)
        changes, prior, diff_error = [], None, None
        try:
            prior, prior_rows, _ = edgar.load_quarter(fetcher, cik, before=meta['period'])
            cur, _ = edgar.build(dict(meta), rows, index, overrides)
            pri, _ = edgar.build(dict(prior), prior_rows, index, overrides)
            changes = edgar.diff(cur, pri)
        except edgar.EdgarError:
            diff_error = 'Prior-period data was unavailable. No comparison has been inferred.'
        # Guess-marked tickers and non-stock securities are visible but cannot be copied.
        for p in positions:
            p['copy_eligible'] = bool(edgar.is_stock(p) and p.get('ticker') and not p.get('ticker_check') and re.fullmatch(r'[A-Z.]{1,10}', p['ticker']))
        result = {'fetched_at': now(), 'meta': meta, 'prior': prior, 'total': total,
                  'positions': positions, 'changes': changes, 'diff_error': diff_error,
                  'filings': filings[:15], 'source': 'SEC EDGAR'}
        save(path, result)
        return result

def congress(year, refresh=False):
    year = int(year)
    if not 2012 <= year <= dt.datetime.now().year: raise ValueError('Select a year from 2012 through the current year.')
    path = PUBLIC / ('congress-' + str(year) + '.json')
    with LOCK:
        previous = cached(path, 900 if refresh else 3600)
        if previous: return previous
        filings = ptr.select(ptr.load_index(year), kind='P')
        result = {'year': year, 'fetched_at': now(), 'source': 'U.S. House Clerk', 'filings': filings}
        save(path, result)
        return result

def report(year, doc):
    if not re.fullmatch(r'\d{5,12}', str(doc)): raise ValueError('Invalid disclosure document ID.')
    year = int(year)
    with LOCK:
        path = PUBLIC / ('report-' + str(year) + '-' + doc + '.json')
        previous = cached(path, 86400)
        if previous: return previous
        entry = next((f for f in congress(year)['filings'] if f['doc_id'] == doc), None)
        if entry is None: raise ValueError('This document is not in the selected House PTR index.')
        pdf = CACHE / (str(year) + '-' + doc + '.pdf')
        CACHE.mkdir(exist_ok=True)
        if not pdf.exists(): pdf.write_bytes(ptr.download(entry['url']))
        text = ptr.pdf_to_text(str(pdf))
        if not text:
            raise ValueError('PDF text extraction is unavailable. Open the official PDF to inspect this report.')
        parsed = ptr.parse_ptr_text(text, filed=entry['filed'])
        if parsed.get('doc_id') and parsed['doc_id'] != doc: raise ValueError('PDF document ID does not match the filing.')
        result = {'fetched_at': now(), 'filing': entry, 'report': parsed,
                  'parse_warning': 'Machine-extracted rows. Verify dates, amounts and completeness against the linked PDF.'}
        save(path, result)
        return result

def bundle(compact=False):
    result = {'catalog': catalog(), 'investors': {}, 'congress': {}, 'reports': {}}
    for p in PUBLIC.glob('*.json'):
        if p.name == 'bundle.json': continue
        item = json.loads(p.read_text(encoding='utf-8'))
        if p.name.startswith('investor-'):
            if not compact or item['meta']['cik'] == '0001067983':
                result['investors'][item['meta']['cik']] = item
        elif p.name.startswith('congress-'): result['congress'][str(item['year'])] = item
        elif p.name.startswith('report-') and not compact: result['reports'][str(item['filing']['year']) + '-' + item['filing']['doc_id']] = item
    save(PUBLIC / 'bundle.json', result)
    return result

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', action='store_true')
    args = parser.parse_args()
    if args.seed:
        year = dt.datetime.now().year
        try:
            house = congress(year)
            print('House PTR index:', len(house['filings']), 'filings', flush=True)
            samples = house['filings'][:5] + [f for f in house['filings'] if 'pelosi' in f['name'].lower()][:3]
            for f in {f['doc_id']: f for f in samples}.values():
                try:
                    r = report(year, f['doc_id'])
                    print('Parsed', f['doc_id'], len(r['report']['rows']), 'rows', flush=True)
                except Exception as exc: print('Report unavailable:', f['doc_id'], type(exc).__name__, flush=True)
        except Exception as exc: print('House index unavailable:', str(exc), flush=True)
        for cik in ['1067983', '1336528', '1350694']:
            try:
                item = investor(cik)
                print('SEC', cik, item['meta']['period'], len(item['positions']), 'positions', flush=True)
            except Exception as exc: print('SEC unavailable:', cik, str(exc), flush=True)
    bundle()
