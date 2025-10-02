from ansible_operator.utils.schedule import compute_computed_schedule


def test_hourly_random_is_valid_and_stable():
    uid = "11111111-1111-1111-1111-111111111111"
    s1, used = compute_computed_schedule("@hourly-random", uid)
    s2, _ = compute_computed_schedule("@hourly-random", uid)
    assert used is True
    assert s1 == s2
    minute, star, *_ = s1.split()
    assert star == "*"
    assert 0 <= int(minute) <= 59


def test_daily_random_is_valid():
    uid = "22222222-2222-2222-2222-222222222222"
    s, used = compute_computed_schedule("@daily-random", uid)
    assert used is True
    minute, hour, *_ = s.split()
    assert 0 <= int(minute) <= 59
    assert 0 <= int(hour) <= 23


def test_weekly_random_is_valid():
    uid = "33333333-3333-3333-3333-333333333333"
    s, used = compute_computed_schedule("@weekly-random", uid)
    assert used is True
    minute, hour, _, _, dow = s.split()
    assert 0 <= int(minute) <= 59
    assert 0 <= int(hour) <= 23
    assert 0 <= int(dow) <= 6


def test_monthly_random_is_valid():
    uid = "44444444-4444-4444-4444-444444444444"
    s, used = compute_computed_schedule("@monthly-random", uid)
    assert used is True
    minute, hour, dom, *_ = s.split()
    assert 0 <= int(minute) <= 59
    assert 0 <= int(hour) <= 23
    assert 1 <= int(dom) <= 28


def test_yearly_random_is_valid():
    uid = "55555555-5555-5555-5555-555555555555"
    s, used = compute_computed_schedule("@yearly-random", uid)
    assert used is True
    minute, hour, dom, month, _ = s.split()
    assert 0 <= int(minute) <= 59
    assert 0 <= int(hour) <= 23
    assert 1 <= int(dom) <= 28
    assert 1 <= int(month) <= 12
