from safespeak.report import percentile, score, wilson_95


def row(label, predicted):
    return {"label": label, "predicted": predicted}


def test_uncertain_scam_is_missed_and_uncertain_legit_is_not_a_false_alarm():
    s = score([row("scam", "scam"), row("scam", "uncertain"), row("legitimate", "scam"),
               row("legitimate", "legitimate"), row("legitimate", "uncertain"), row("scam", "")])
    assert (s.tp, s.fn, s.fp, s.tn) == (1, 1, 1, 2)
    assert s.uncertain == 2 and s.errors == 1 and s.n == 6
    assert s.precision == 0.5 and s.recall == 0.5 and s.false_alarm_rate == 1 / 3


def test_wilson_interval_is_wide_for_small_samples():
    low, high = wilson_95(5, 6)
    assert low < 0.5 and high > 0.95
    assert wilson_95(0, 0) == (0.0, 0.0)


def test_percentile():
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
