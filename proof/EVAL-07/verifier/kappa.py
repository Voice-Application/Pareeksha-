import csv,json,sys
sys.path.insert(0,'backend')
from pareeksha.evaluation.calibration import compute_calibration, LabelPair
import inspect; print(inspect.signature(LabelPair))
def run(labels,key,judge):
    k=json.load(open(key)); k=k.get('labels',k) if isinstance(k,dict) else k
    j={r['call_id']:r for r in json.load(open(judge))}
    rows=list(csv.DictReader(open(labels)))
    ps=[];ids=[]
    for r in rows:
        cid=k[r['label_id']]; cid=cid['call_id'] if isinstance(cid,dict) else cid
        if cid is None: print('nokey',r['label_id']);continue
        hp=r['passed'].strip().lower()=='yes'
        jr=j[cid]
        ps.append(LabelPair(judge_passed=jr['passed'],human_passed=hp,judge_score=None,human_score=None,judge_dimensions={},human_dimensions={})); 
        ids.append((r['label_id'],jr['passed'],hp))
    print(len(ps),compute_calibration(ps).kappa_pass_fail, 'hum pass',sum(p.human_passed for p in ps),'judge pass',sum(p.judge_passed for p in ps))
    return ids
run(*sys.argv[1:4])
