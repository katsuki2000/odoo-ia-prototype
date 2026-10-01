from code_intelligence.evaluation.resolver_metrics import summarize_evaluation


def test_candidate_domain_recall_is_reported_separately_from_accuracy():
    metrics = summarize_evaluation([
        {
            "answered": False, "correct": False, "candidate_domain_rank": 2,
            "candidate_domain_evaluable": True,
        },
        {"answered": True, "correct": True, "candidate_domain_evaluable": False},
        {
            "answered": False, "correct": False, "candidate_domain_rank": None,
            "candidate_domain_evaluable": True,
        },
    ])

    assert metrics["accuracy_all_questions"] == 1 / 3
    assert metrics["candidate_domain_questions"] == 2
    assert metrics["candidate_domain_recall_at_1"] == 0
    assert metrics["candidate_domain_recall_at_3"] == 0.5
    assert metrics["candidate_domain_recall_at_5"] == 0.5
