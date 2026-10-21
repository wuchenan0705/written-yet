"""Cases taken from real submissions in the database."""
from app import judge
from app.models import BLANK, CORRECT, UNGRADED, WRONG

MATCH_BOX = {"A": "people may think the restaurant is overpriced", "B": "people would come back again",
             "C": "people would spend more money", "F": "people would likely make complaints"}
YEARS = {"A": "15 years ago", "B": "30 years ago", "C": "60 years ago"}


def fill(user, key):
    return judge.judge("fill", user, judge.split_key("fill", key, {}), {})


def test_fill_answers():
    assert fill("craswick", "Creswick") == WRONG
    assert fill("creswick", "Creswick") == CORRECT
    assert fill("june 13", "13th June/June 13th/13 June/June 13") == CORRECT
    assert fill("13 jun", "June 13th") == CORRECT
    assert fill("5:30", "5.30/5:30") == CORRECT
    assert fill("5.30", "5:30") == CORRECT
    assert fill("online", "internet") == WRONG
    assert fill("comedy", "comic/comedy") == CORRECT
    assert fill("Leaflet.", "leaflet") == CORRECT
    assert fill("leaflets", "(the) leaflet(s)") == CORRECT
    assert fill("the leaflet", "(the) leaflet(s)") == CORRECT
    assert fill("1,000", "1000") == CORRECT
    assert fill("未作答", "theatre") == BLANK
    assert fill("-", "theatre") == BLANK
    assert fill("milk", "") == UNGRADED


def test_option_letters():
    assert judge.to_letter("C   people would spend more money", MATCH_BOX) == "C"
    assert judge.to_letter("A. competitors nearby", {}) == "A"
    assert judge.to_letter("(b)", {}) == "B"
    assert judge.to_letter("ｂ", {}) == "B"  # full-width
    assert judge.to_letter("people would come back again", MATCH_BOX) == "B"
    assert judge.to_letter("30 years ago", YEARS) == "B"
    assert judge.to_letter("a previous study", {}) is None  # lower-case article, not a letter
    assert judge.to_letter("something else", MATCH_BOX) is None
    assert judge.judge("matching", "C people would spend more money", ["C"], MATCH_BOX) == CORRECT
    assert judge.judge("matching", "B involve more children in need", ["E"], {}) == WRONG
    assert judge.judge("matching", "F", ["people may think the restaurant is overpriced"], MATCH_BOX) == WRONG
    assert judge.judge("matching", "A", ["people may think the restaurant is overpriced"], MATCH_BOX) == CORRECT
    assert judge.judge("choice", "B", ["30 years ago"], YEARS) == CORRECT
    assert judge.judge("choice", "30 years ago", ["B"], YEARS) == CORRECT


def test_letters_only_stripped_for_option_questions():
    assert judge.canon("fill", "A lot", {}) == "A lot"
    assert judge.canon("choice", "A lot", {}) == "A"
    assert judge.canon("tfng", "no", {}) == "NO"
    assert judge.canon("tfng", "ng", {}) == "NOT GIVEN"
    assert judge.judge("tfng", "ng", ["NOT GIVEN"], {}) == CORRECT
    assert judge.judge("tfng", "N", ["NO"], {}) == CORRECT
    assert judge.judge("tfng", "NO", ["NOT GIVEN"], {}) == WRONG
    # A key that is a TFNG word is judged as TFNG even if the kind was guessed wrong.
    assert judge.judge("fill", "f", ["FALSE"], {}) == CORRECT


def test_split_key():
    assert judge.split_key("fill", "theater/theatre", {}) == ["theater", "theatre"]
    assert judge.split_key("multi", "A, E", {}) == ["A", "E"]
    assert judge.split_key("multi", "A and E", {}) == ["A", "E"]
    assert judge.split_key("multi", "A/E", {}) == ["A", "E"]
    assert judge.split_key("choice", "C earn support from colleges", {}) == ["C"]
    assert judge.split_key("tfng", "NG", {}) == ["NOT GIVEN"]


def test_choose_two_any_order_each_letter_once():
    assert judge.judge_group([("E", ["A", "E"]), ("A", ["A", "E"])], {}) == [CORRECT, CORRECT]
    assert judge.judge_group([("A", ["A", "E"]), ("A", ["A", "E"])], {}) == [CORRECT, WRONG]
    assert judge.judge_group([("A", ["A", "E"]), ("", ["A", "E"])], {}) == [CORRECT, BLANK]
    assert judge.judge_group([("A", []), ("D", [])], {}) == [UNGRADED, UNGRADED]


def test_guess_error_type():
    assert judge.guess_error_type("fill", "craswick", ["Creswick"]) == "拼字錯誤"
    assert judge.guess_error_type("fill", "warring", ["warning"]) == "拼字錯誤"
    assert judge.guess_error_type("fill", "box", ["boxes"]) == "單複數/詞形"
    assert judge.guess_error_type("fill", "online", ["internet"]) is None
    assert judge.guess_error_type("fill", "14", ["40"]) == "數字/日期"
    assert judge.guess_error_type("fill", "", ["bins"]) == "未作答"
    assert judge.guess_error_type("tfng", "FALSE", ["NOT GIVEN"]) == "NOT GIVEN/FALSE 混淆"
    assert judge.guess_error_type("tfng", "YES", ["NO"]) is None
    assert judge.guess_error_type("choice", "B", ["E"]) is None
