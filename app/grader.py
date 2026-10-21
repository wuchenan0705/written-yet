"""Read a pasted IELTS practice set with Claude and return structured feedback.

For listening/reading Claude transcribes each question (the student's answer and the key)
and writes the explanations; judge.py decides right or wrong.
"""
import base64
import json
from typing import Sequence

import anthropic

from app import config
from app.models import ANSWER_KINDS, ERROR_TYPES, SKILL_ZH

KINDS_HELP = """kind（題型）：
- fill：寫字或數字的題（填空、簡答、表格、摘要、流程圖、地圖標示）
- choice：單選題（A/B/C/D 選一個）
- matching：配對題，從一個共用選項框選字母（如 A-F、i-x 標題配對也算，羅馬數字當字母照抄）
- tfng：TRUE/FALSE/NOT GIVEN 或 YES/NO/NOT GIVEN
- multi：多選題（Choose TWO/THREE letters），每個題號各一筆，group 填整組題號如 "25-26"，answer_key 填整組全部正解（如 "A/E"），user_answer 依序填學生在該題號選的一個字母

options（choice/matching/multi 一定要填，其他題型給空陣列）：
- letter 用大寫字母，text 是選項文字。
- 從雅思哥複製文字時，單選題選項前的字母會消失，依出現順序補 A、B、C…。
- 配對題的選項框：學生選過的選項會被拖到題目旁邊（例如題目後面接著「B   involve more children in need」就是選項 B 的文字），沒被選的會留在最後。把這兩部分合併成整組選項，同一組的每題都列同一份。只知道字母、看不到文字的選項照樣列出，text 留空字串。
- 選項題的 user_answer 和 answer_key 只填字母（"B"），不要填文字。"""

SYSTEM_PROMPT = f"""你是一位嚴格但友善的雅思（IELTS）教練，學生用「雅思哥」練習後把結果交給你批改。用繁體中文回饋，英文例句保留英文。

學生交來的內容可能是以下任一種或混合：
- 雅思哥檢討頁的截圖：每組題目下方的框裡有「正确答案」和「我的答案」，以它為準；單選題被選中的選項有實心圓點。
- 從雅思哥複製的文字：單選題和 YES/NO/NOT GIVEN 的勾選狀態會在複製時遺失，只剩選項文字；填空/拖曳題的答案會留在題目裡，那是學生的答案。「解析」字樣是摺疊的解析按鈕，忽略即可。
- 學生自己打的答案列，例如「27A 28A 29C 37 NO」或「我的答案：…／正確答案：…」。

聽力 / 閱讀：你負責「把每一題讀出來」和「寫解析」，對錯由系統比對 user_answer 和 answer_key 決定，你不用判斷。
- questions：本次範圍內每一題各一筆，依題號排序，不要漏題、不要重複。question_no 只填數字（如 "37"）。
- question_range：本次的第一題和最後一題題號（從「Questions 21-24」這類標題判斷；看不出來兩個都填 0）。
- question 填題目原句（填空題寫成 "name: Jan ___" 這種形式）。
{KINDS_HELP}
- user_answer：照抄學生寫的，拼錯也照抄，不要幫他改。學生沒作答（空格、「未作答」、「-」）填空字串，answer_visible 填 true。
- answer_visible：只有「資訊遺失、看不出學生答了什麼」才填 false（例如複製文字時單選題的勾選消失，又沒有截圖或答案列可對照），user_answer 留空。不要猜。
- answer_key：頁面上有「正确答案」就照抄，key_source 填 "page"；多個可接受寫法用 / 分隔（如 "theater/theatre"）。頁面上沒有就由你依原文解題，key_source 填 "coach"。tfng 題填全稱（TRUE / FALSE / NOT GIVEN / YES / NO）。
- note：每題都寫，一句話點出關鍵（例如同義替換 "ubiquitous ↔ widely available"）。evidence 填原文或聽力稿中能定位答案的那句（沒有原文就留空）。
- 你認為學生答錯、沒作答，或 answer_visible 是 false 的題目：explanation 說明正解為何成立（答錯的話也說明學生為什麼錯），tip 給下次遇到同類題的具體做法，error_type 從這些類別擇一：{"、".join(ERROR_TYPES)}。key_source 是 "coach" 時 explanation 開頭註明「（教練判斷）」。你認為答對的題目 explanation、tip、error_type 留空字串。

寫作：question_count 填 1。band_estimate 給整體預估分數（如 "6.0"），criteria 依 TR、CC、LR、GRA 四項各給分數與評語，corrections 挑出最重要的錯誤句改寫並說明，improved_version 改寫一段最弱的段落到 7 分水準。questions 留空陣列。
口說：學生貼的是自己的回答文字。question_count 填回答的題數。band_estimate 給預估分數，criteria 依 FC、LR、GRA 給評語（發音無法從文字判斷就略過），corrections 指出用詞和文法問題，improved_version 給一個高分版本的示範回答。questions 留空陣列。
聽力 / 閱讀的 question_count 填 0（由系統計算）。

source：從截圖標題（如「C21-Test 1-Passage 3」）或文字判斷出處。book 用簡寫（劍橋雅思 21 → "C21"），test 如 "Test 1"，part 如 "Passage 3"、"Section 2"、"Part 2"、"Task 2"，title 是文章或題目標題（如 "The World of Sugar"）。看不出來就留空，不要編。

不適用的欄位給空字串或空陣列。summary 用一兩句話總結這次的表現與最該改進的一點。"""


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_S = {"type": "string"}
_OPTIONS = {"type": "array", "items": _obj({"letter": _S, "text": _S})}
_ERROR_TYPE = {"type": "string", "enum": ERROR_TYPES + [""]}
QUESTION = _obj({
    "question_no": _S,
    "kind": {"type": "string", "enum": list(ANSWER_KINDS)},
    "group": _S,
    "question": _S,
    "options": _OPTIONS,
    "user_answer": _S,
    "answer_visible": {"type": "boolean"},
    "answer_key": _S,
    "key_source": {"type": "string", "enum": ["page", "coach"]},
    "error_type": _ERROR_TYPE,
    "note": _S,
    "explanation": _S,
    "evidence": _S,
    "tip": _S,
})
SCHEMA = _obj({
    "question_count": {"type": "integer"},
    "summary": _S,
    "source": _obj({"book": _S, "test": _S, "part": _S, "title": _S}),
    "question_range": _obj({"first": {"type": "integer"}, "last": {"type": "integer"}}),
    "questions": {"type": "array", "items": QUESTION},
    "band_estimate": _S,
    "criteria": {"type": "array", "items": _obj({"name": _S, "band": _S, "comment": _S})},
    "corrections": {"type": "array", "items": _obj({"original": _S, "corrected": _S, "reason": _S})},
    "improved_version": _S,
})


class GradingError(Exception):
    pass


_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _image_blocks(images: Sequence[tuple[str, bytes]]) -> list[dict]:
    return [
        {"type": "image", "source": {"type": "base64", "media_type": mt,
                                     "data": base64.b64encode(data).decode()}}
        for mt, data in images
    ]


def _call(system: str, content: list[dict], schema: dict) -> dict:
    try:
        # Streamed so a 40-question set with explanations isn't cut off by HTTP timeouts.
        with _get_client().beta.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
        ) as stream:
            response = stream.get_final_message()
    except anthropic.APIConnectionError as e:
        raise GradingError("連不上 Claude API，請稍後再試。") from e
    except anthropic.RateLimitError as e:
        raise GradingError("Claude API 忙碌中（rate limit），請稍後再試。") from e
    except anthropic.APIStatusError as e:
        raise GradingError(f"Claude API 錯誤（{e.status_code}）：{e.message}") from e
    except anthropic.AnthropicError as e:  # e.g. missing API key
        raise GradingError(f"Claude 設定錯誤：{e}") from e

    if response.stop_reason == "refusal":
        raise GradingError("Claude 拒絕處理這段內容，請檢查貼上的文字。")
    if response.stop_reason == "max_tokens":
        raise GradingError("內容太長，回饋被截斷了，請分批提交。")
    texts = [b.text for b in response.content if b.type == "text"]
    if not texts:
        raise GradingError("Claude 沒有回傳結果。")
    return json.loads(texts[-1])


def grade(skill: str, text: str, images: Sequence[tuple[str, bytes]] = ()) -> dict:
    """images: (media_type, data) pairs, e.g. screenshots of the 雅思哥 review page."""
    content = _image_blocks(images)
    content.append({"type": "text", "text": f"科目：{SKILL_ZH[skill]}\n\n{text or '（內容在截圖裡）'}"})
    result = _call(SYSTEM_PROMPT, content, SCHEMA)
    if skill == "writing":
        result["question_count"] = 1
    result["question_count"] = max(0, int(result.get("question_count") or 0))
    return result


EXPLAIN_PROMPT = f"""你是雅思（IELTS）教練。學生之前交過一份{{skill}}練習，系統已經比對過答案，現在需要你替下面列出的題目補上解析。只處理列出的題號，題號照抄。

每一題：
- 有提供正解：answer_key 照抄，key_source 填 "page"。沒提供正解：依原始內容（文章、聽力稿、題目、截圖）解題，answer_key 填正解，key_source 填 "coach"，explanation 開頭註明「（教練判斷）」。
- 題型與選項照下面的寫法；已經列出的選項照抄。

{KINDS_HELP}

- 學生答案和正解不同或沒作答：explanation 說明學生為什麼錯、正解為何成立，tip 給下次的做法，error_type 從這些擇一：{"、".join(ERROR_TYPES)}。答案相同：explanation、tip、error_type 留空。
- note 一句話點出關鍵，evidence 填定位句，question 填題目原句。
- 學生答案常用縮寫：NG = NOT GIVEN，T / F = TRUE / FALSE，Y / N = YES / NO，大小寫不重要。
- 用繁體中文，英文原句保留英文。"""

EXPLAIN_ITEM = _obj({k: QUESTION["properties"][k] for k in (
    "question_no", "kind", "question", "options", "answer_key", "key_source",
    "error_type", "note", "explanation", "evidence", "tip")})
EXPLAIN_SCHEMA = _obj({"items": {"type": "array", "items": EXPLAIN_ITEM}})


def explain(skill: str, original_text: str, images: Sequence[tuple[str, bytes]],
            questions: Sequence[dict]) -> list[dict]:
    """Explanations (and a key, when there is none) for already-judged questions.

    questions: dicts with question_no, kind, question, options, user_answer, answer_key.
    """
    lines = []
    for q in questions:
        line = f"第 {q['question_no']} 題（{q['kind']}）"
        if q.get("question"):
            line += f"：{q['question']}"
        if q.get("options"):
            line += "\n  選項：" + "；".join(f"{k} {v}".strip() for k, v in q["options"].items())
        line += f"\n  學生答案：{q['user_answer'] or '（未作答）'}"
        line += f"\n  正解：{q['answer_key']}" if q.get("answer_key") else "\n  正解：（請你判斷）"
        lines.append(line)
    content = _image_blocks(images)
    content.append({"type": "text", "text": (
        f"原始提交內容：\n{original_text or '（內容在截圖裡）'}\n\n需要解析的題目：\n" + "\n".join(lines)
    )})
    result = _call(EXPLAIN_PROMPT.format(skill=SKILL_ZH[skill]), content, EXPLAIN_SCHEMA)
    asked = {str(q["question_no"]) for q in questions}
    return [i for i in result.get("items", []) if i["question_no"].strip() in asked]
