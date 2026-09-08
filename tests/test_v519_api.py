import pytest
from test_v5_1_9_development import fixture

from formulaguard.api import localize


@pytest.mark.parametrize("method", ["v5.1.9-development", "v5_1_9_development", "v519-development"])
@pytest.mark.parametrize("backend", ["v4", "v511"])
@pytest.mark.parametrize("policy", ["structural", "review_only", "reject_all"])
def test_local_python_api_aliases_preserve_ranking_and_policy(method, backend, policy):
    model, ranking, args, _ = fixture(backend=backend)
    results = localize(model, method=method, localization_backend=backend, repair_policy=policy,
                       **{k: v for k, v in args.items() if k != "backend"})
    assert [(r.cell, r.score.hex()) for r in results] == [(r.cell, r.score.hex()) for r in ranking]
    assert all(r.evidence["model_version"] == "v5.1.9-development" for r in results)
    assert sum(r.candidate_formula is not None for r in results) == (4 if policy == "structural" else 0)
    assert all(r.evidence["search_status"] == "unique_solution" for r in results)
