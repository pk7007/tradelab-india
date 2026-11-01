"""Run offline checks and write an auditable report; no broker calls."""
import datetime as dt
import io
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from validation_lab import stress_suite

class RecordedResult(unittest.TextTestResult):
    records=[]
    def addSuccess(self,test):
        super().addSuccess(test)
        self.records.append((test.id(),'PASS','All assertions passed'))
    def addFailure(self,test,err):
        super().addFailure(test,err)
        self.records.append((test.id(),'FAIL',self._exc_info_to_string(err,test)))
    def addError(self,test,err):
        super().addError(test,err)
        self.records.append((test.id(),'ERROR',self._exc_info_to_string(err,test)))
    def addSkip(self,test,reason):
        super().addSkip(test,reason)
        self.records.append((test.id(),'NOT RUN',reason))

suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite)
lines=['# Offline research test results','',
       'Executed: '+dt.datetime.now(dt.timezone.utc).isoformat(),
       'Command: `.\\.venv\\Scripts\\python.exe scripts/check_research.py`',
       'Fixtures: synthetic OHLCV, seeded synthetic paths, and in-memory mock job/order state only. No live account operations.',
       'Expected for each test: the named invariant holds under the fixtures and assertions in its linked test function.',
       'Actual results below. Excluded/not-run integration scenarios are listed in [implementation status](research-implementation.md).','',
       '| Test / expected invariant | Fixture source | Actual | Status |','| --- | --- | --- | --- |']
for name,status,actual in result.records:
    module,cls,method=name.split('.')
    expected=method.removeprefix('test_').replace('_',' ')
    lines.append('| '+expected+' | ['+cls+'](../tests/'+module+'.py) | '+actual.replace('\n',' ').replace('|','/')+' | '+status+' |')
(ROOT/'docs'/'research-test-results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(ROOT/'docs'/'synthetic-stress-results.json').write_text(json.dumps(stress_suite(),indent=2,allow_nan=False),encoding='utf-8')
sys.exit(0 if result.wasSuccessful() else 1)
