"""Capture both collected and actually executed identities and source for one pytest session."""
import json,os
from pathlib import Path
from cne.platform.evidence import source_identity
_session=None

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf8')
def pytest_sessionstart(session):
    global _session
    _session=session;session._cne_records={};session._cne_source=source_identity(session.config.rootpath)
def pytest_collection_finish(session):
    session._cne_collected=sorted(item.nodeid for item in session.items)
    for item in session.items:item.user_properties.append(('cne_nodeid',item.nodeid))
    target=os.environ.get('CNE_TEST_INVENTORY_PATH')
    if target:write(target,session._cne_collected)
def pytest_runtest_logreport(report):
    if _session is None:return
    record=_session._cne_records.setdefault(report.nodeid,{'nodeid':report.nodeid,'phases':{}})
    record['phases'][report.when]={'outcome':report.outcome,'duration':report.duration,'wasxfail':bool(getattr(report,'wasxfail',False)),
                                  'reason':str(report.longrepr) if report.outcome in ('skipped','failed') else None}
def pytest_sessionfinish(session,exitstatus):
    target=os.environ.get('CNE_TEST_EXECUTION_PATH')
    if target:write(target,{'schema':'cne-pytest-execution-2','source_start':session._cne_source,'source_end':source_identity(session.config.rootpath),
                           'collected':getattr(session,'_cne_collected',[]),'records':[session._cne_records[k] for k in sorted(session._cne_records)],'exit_code':int(exitstatus)})
