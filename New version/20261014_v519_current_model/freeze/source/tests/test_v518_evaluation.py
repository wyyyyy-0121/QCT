import json
import shutil

import pytest

from scripts import evaluate_v518_numeric as workflow
from scripts.run_v512_evaluation import write_json
from scripts.score_v512_confirmation import sha256


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root=tmp_path_factory.mktemp("v518-protocol")
    workflow.build(root/"release","test")
    workflow.predict(root/"release",root/"predictions",workers=1)
    workflow.score(root/"release",root/"predictions",root/"score",workers=1)
    result=json.loads((root/"score/result.json").read_text())
    assert result["gate_passed"] and result["diagnoses"]==36
    assert result["summaries"]["v4_numeric"]["unsafe_groups"]==0
    return root


@pytest.mark.parametrize("defect",["missing","ranking","budget","proof","runtime"])
def test_tampered_evidence_rejected_before_label_authorization(prepared,tmp_path,defect):
    predictions=tmp_path/"predictions"
    shutil.copytree(prepared/"predictions",predictions)
    lockpath=predictions/"prediction_lock.json"
    lock=json.loads(lockpath.read_text())
    name=next(name for name in lock["shards"] if name.startswith("shards/v4_numeric/")
              and json.loads((predictions/name).read_text())["diagnosis"]["search"]["status"]=="unique_solution")
    path=predictions/name
    shard=json.loads(path.read_text())
    if defect=="missing":
        path.unlink()
        del lock["shards"][name]
    else:
        if defect=="ranking":
            shard["diagnosis"]["localization"][0]["score"]+=123
        elif defect=="budget":
            shard["configuration"]["max_nodes"]+=1
        elif defect=="proof":
            shard["diagnosis"]["search"]["terminals"].pop(0)
        else:
            shard["diagnosis"]["search"]["runtime_json"]="changed"
        write_json(path,shard)
        lock["shards"][name]=sha256(path)
    write_json(lockpath,lock)
    with pytest.raises(ValueError):
        workflow.score(prepared/"release",predictions,tmp_path/"score",workers=1)
    assert not (tmp_path/"score/reveal_authorization.json").exists()


def test_self_consistent_population_deletion_still_fails(prepared,tmp_path):
    release=tmp_path/"release"
    shutil.copytree(prepared/"release",release)
    manifest=json.loads((release/"PUBLIC/manifest.json").read_text())
    manifest["cases"].pop()
    write_json(release/"PUBLIC/manifest.json",manifest)
    receipt=json.loads((release/"release_receipt.json").read_text())
    receipt["cases"]-=1
    receipt["manifest_sha256"]=sha256(release/"PUBLIC/manifest.json")
    write_json(release/"release_receipt.json",receipt)
    with pytest.raises(ValueError,match="predeclared population"):
        workflow.release_context(release)


def test_confirmation_requires_freeze(tmp_path):
    with pytest.raises(ValueError,match="prior source freeze"):
        workflow.build(tmp_path/"confirmation","confirmation")


def test_specification_sizes_and_fixed_budgets():
    assert len(workflow.specifications("development"))==48
    assert len(workflow.specifications("confirmation"))==144
    for mode in workflow.MODES:
        config,_=workflow.configuration(mode)
        assert config.max_evaluations==4096 and config.max_preparations==4096
        assert config.max_nodes==(1 if mode=="low_budget" else 10000)
