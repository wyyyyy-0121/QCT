import json
import shutil
from pathlib import Path

import pytest

from scripts.evaluate_v519_confirmation import build, freeze, predict, score
from scripts.v518_validation_common import sha256, write_json


@pytest.fixture(scope="module")
def prediction(tmp_path_factory):
    root=tmp_path_factory.mktemp("v519-evaluation")
    release,output=root/"release",root/"predictions"
    build(release,"test")
    predict(release,output,workers=2)
    return release,output


def test_full_prediction_verification_precedes_label_read(prediction,tmp_path,monkeypatch):
    release,predictions=prediction
    original=Path.read_text
    output=tmp_path/"score"

    def guarded(path,*args,**kwargs):
        if path==release/"labels.json":
            assert (output/"reveal_authorization.json").is_file()
        return original(path,*args,**kwargs)

    monkeypatch.setattr(Path,"read_text",guarded)
    score(release,predictions,output,workers=2)
    result=json.loads((output/"result.json").read_text())
    assert result["safe"] and result["workbooks"]==3 and result["diagnoses"]==36


@pytest.mark.parametrize("defect",["missing","extra","budget","policy","ranking","proof","population","source","environment","labels_read"])
def test_tampering_rejected_before_reveal(prediction,tmp_path,defect):
    release,original=prediction
    predictions=tmp_path/"predictions"
    shutil.copytree(original,predictions)
    lock=json.loads((predictions/"prediction_lock.json").read_text())
    name=next(n for n in lock["shards"] if "/v4_main/" in n)
    path=predictions/name
    shard=json.loads(path.read_text())
    if defect=="missing":
        path.unlink()
    elif defect=="extra":
        write_json(predictions/"shards/extra.json",{})
    elif defect=="population":
        lock["cases"]-=1
    elif defect=="source":
        lock["sources"]={}
    elif defect=="environment":
        lock["environment"]={}
    elif defect=="labels_read":
        lock["labels_read"]=["labels.json"]
    else:
        if defect=="budget":
            shard["configuration"]["max_nodes"]+=1
        elif defect=="policy":
            shard["policy"]="review_only"
        elif defect=="ranking":
            shard["diagnosis"]["localization"].reverse()
        else:
            shard["diagnosis"]["search"]["table_sha256"]="changed"
            # Select an actual unique shard, rather than an abstention shard.
            for n in lock["shards"]:
                if "/v4_main/" in n:
                    candidate=json.loads((predictions/n).read_text())
                    if candidate["diagnosis"]["search"]["status"]=="unique_solution":
                        name,path,shard=n,predictions/n,candidate
                        shard["diagnosis"]["search"]["table_sha256"]="changed"
                        break
        write_json(path,shard)
        lock["shards"][name]=sha256(path)
    write_json(predictions/"prediction_lock.json",lock)
    output=tmp_path/"score"
    with pytest.raises(ValueError):
        score(release,predictions,output,workers=2)
    assert not (output/"reveal_authorization.json").exists()


def test_confirmation_requires_freeze_and_preserves_matrix(tmp_path):
    with pytest.raises(ValueError,match="prior freeze"):
        build(tmp_path/"unfrozen","confirmation")
    frozen=tmp_path/"frozen"
    freeze(frozen)
    lock=json.loads((frozen/"source_lock.json").read_text())
    assert len(lock["specifications"])==144 and len(lock["modes"])==6
    lock["specifications"].pop()
    write_json(frozen/"source_lock.json",lock)
    with pytest.raises(ValueError,match="matrix changed"):
        build(tmp_path/"release","confirmation",frozen/"source_lock.json")
