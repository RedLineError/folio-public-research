"""Refresh only public research. Never reads or exports portfolio files."""
import datetime as dt
import os
import sys
from research import congress, report, investor, catalog, bundle

if not os.environ.get('SEC_USER_AGENT'):
    sys.exit('Configure the SEC_USER_AGENT repository secret before running this job.')

failures=[]
year=dt.datetime.now(dt.timezone.utc).year
try:
    index=congress(year,True)
    print('House index:',len(index['filings']),'reports',flush=True)
    for filing in index['filings']:
        try: report(year,filing['doc_id'])
        except Exception as exc:
            failures.append('House '+filing['doc_id']+' '+type(exc).__name__)
except Exception as exc: failures.append('House index '+type(exc).__name__)
for filer in catalog()['filers']:
    try:
        result=investor(filer['cik'],True)
        print('SEC',filer['cik'],result['meta']['period'],flush=True)
    except Exception as exc: failures.append('SEC '+filer['cik']+' '+type(exc).__name__)
bundle(compact=True)
if failures:
    print('\n'.join(failures),file=sys.stderr)
    sys.exit('Some sources failed. Successful public snapshots were retained; the run is marked failed.')
print('Public research refresh complete. No portfolio or broker data accessed.')
