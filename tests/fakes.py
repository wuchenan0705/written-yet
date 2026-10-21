"""Builders for fake grader output in the new per-question schema."""


def q(no, kind="fill", user="", key="", visible=True, options=(), group="", error_type="",
      explanation="", note="", key_source="page"):
    return {
        "question_no": no, "kind": kind, "group": group, "question": f"Q{no}",
        "options": [{"letter": letter, "text": text} for letter, text in options],
        "user_answer": user, "answer_visible": visible, "answer_key": key, "key_source": key_source,
        "error_type": error_type, "note": note, "explanation": explanation, "evidence": "", "tip": "",
    }


def result(questions=(), first=0, last=0, source=None, **extra):
    return {
        "question_count": 0, "summary": "",
        "source": source or {"book": "", "test": "", "part": "", "title": ""},
        "question_range": {"first": first, "last": last}, "questions": list(questions),
        "band_estimate": "", "criteria": [], "corrections": [], "improved_version": "", **extra,
    }


def explainer(items=None):
    """Fake grader.explain: records calls, returns an explanation for each question asked."""
    calls = []

    def explain(skill, text, images, questions):
        calls.append([dict(x) for x in questions])
        out = []
        for x in questions:
            item = {"question_no": x["question_no"], "kind": x["kind"], "question": x["question"],
                    "options": [{"letter": k, "text": v} for k, v in x["options"].items()],
                    "answer_key": x["answer_key"], "key_source": "page", "error_type": "",
                    "note": "", "explanation": f"解析 {x['question_no']}", "evidence": "", "tip": ""}
            item.update((items or {}).get(x["question_no"], {}))
            out.append(item)
        return out
    return explain, calls
