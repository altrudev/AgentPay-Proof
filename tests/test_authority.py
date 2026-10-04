from src.model import Intent, decide
from src.demo import run

def test_over_limit_denied_before_settlement():
    r = run("2.00")
    assert r["authority"]["decision"] == "DENY"
    assert r["settlement"] is None

def test_permitted_demo_has_observation():
    r = run("0.50")
    assert r["authority"]["decision"] == "PERMIT"
    assert r["settlement"]["chain"] == "base"
    assert r["observation"]["outcome"] == "MATCH"

def test_wrong_recipient_denied():
    i=Intent("a","svc","0xBad","0.10")
    assert decide(i,"1.00","0xGood","svc").decision == "DENY"
