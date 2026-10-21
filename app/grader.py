"""Grade a pasted IELTS practice set with Claude and return structured feedback."""
import base64
import json
from typing import Sequence

import anthropic

from app import config
from app.models import SKILL_ZH

ERROR_TYPES = [
    "未作答", "同義替換沒認出", "NOT GIVEN/FALSE 混淆", "定位錯誤", "細節漏看", "拼字錯誤",
    "單複數/詞形", "字數限制", "數字/日期", "詞彙不認識", "推論/邏輯", "文法", "其他",
]

SYSTEM_PROMPT = f"""你是一位嚴格但友善的雅思（IELTS）教練，學生用「雅思哥」練習後把結果交給你批改。用繁體中文回饋，英文例句保留英文。

學生交來的內容可能是以下任一種或混合：
- 雅思哥檢討頁的截圖：每組題目下方的框裡有「正确答案」和「我的答案」，以它為準；單選題被選中的選項有實心圓點。
- 從雅思哥複製的文字：單選題和 YES/NO/NOT GIVEN 的勾選狀態會在複製時遺失，只剩選項文字；拖曳/填空題的答案（如「H migrant workers」）會留在題目裡，那是學生的答案。「解析」字樣是摺疊的解析按鈕，忽略即可。
- 學生自己打的答案列，例如「27A 28A 29C 37 NO」或「我的答案：…／正確答案：…」。

規則：
- 找不到正確答案的題目，由你依原文解題判斷，並在 explanation 開頭註明「（教練判斷）」。
- 學生沒作答的題目算錯：填空/拖曳題的空格是空的、截圖「我的答案」那題是空白或「-」、或學生的答案列明確跳過某題，都放進 mistakes，user_answer 填空字串，error_type 填「未作答」，照樣解釋正解與定位句。
- 只有「資訊遺失、無法判斷學生答了什麼」才放進 missing_answers（例如複製文字時單選題的勾選消失，又沒有截圖或答案列可對照），不要猜，也不計入 question_count 和 correct_count。空白的填空不是這種情況。

依科目處理：
- 聽力 / 閱讀：逐題比對。question_count 是本次的總題數，correct_count 是答對題數。每一題答錯都放進 mistakes，答對的放進 correct_items，兩者都依題號排序、question_no 填題號（如 "37"）。correct_items 的 note 用一句話點出這題的關鍵（例如同義替換 "ubiquitous ↔ widely available"），evidence 填定位句。mistakes 的 error_type 從這些類別擇一：{"、".join(ERROR_TYPES)}。evidence 填原文或聽力稿中能定位答案的那句（沒有原文就留空），explanation 說明為什麼錯、正確答案為何成立，tip 給下次遇到同類題的具體做法。
- 寫作：question_count 填 1、correct_count 填 0。band_estimate 給整體預估分數（如 "6.0"），criteria 依 TR、CC、LR、GRA 四項各給分數與評語，corrections 挑出最重要的錯誤句改寫並說明，improved_version 改寫一段最弱的段落到 7 分水準。mistakes 留空陣列。
- 口說：學生貼的是自己的回答文字。question_count 為回答的題數、correct_count 填 0。band_estimate 給預估分數，criteria 依 FC、LR、GRA 給評語（發音無法從文字判斷就略過），corrections 指出用詞和文法問題，improved_version 給一個高分版本的示範回答。mistakes 留空陣列。

source：從截圖標題（如「C21-Test 1-Passage 3」）或文字判斷出處。book 用簡寫（劍橋雅思 21 → "C21"），test 如 "Test 1"，part 如 "Passage 3"、"Section 2"、"Part 2"、"Task 2"，title 是文章或題目標題（如 "The World of Sugar"）。看不出來就留空，不要編。

不適用的欄位給空字串或空陣列。summary 用一兩句話總結這次的表現與最該改進的一點。"""


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_S = {"type": "string"}
SCHEMA = _obj({
    "question_count": {"type": "integer"},
    "correct_count": {"type": "integer"},
    "summary": _S,
    "source": _obj({"book": _S, "test": _S, "part": _S, "title": _S}),
    "mistakes": {"type": "array", "items": _obj({
        "question_no": _S,
        "question": _S,
        "user_answer": _S,
        "correct_answer": _S,
        "error_type": {"type": "string", "enum": ERROR_TYPES},
        "explanation": _S,
        "evidence": _S,
        "tip": _S,
    })},
    "correct_items": {"type": "array", "items": _obj({
        "question_no": _S,
        "question": _S,
        "answer": _S,
        "note": _S,
        "evidence": _S,
    })},
    "band_estimate": _S,
    "criteria": {"type": "array", "items": _obj({"name": _S, "band": _S, "comment": _S})},
    "corrections": {"type": "array", "items": _obj({"original": _S, "corrected": _S, "reason": _S})},
    "improved_version": _S,
    "missing_answers": {"type": "array", "items": _S},
})


class GradingError(Exception):
    pass


_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def grade(skill: str, text: str, images: Sequence[tuple[str, bytes]] = ()) -> dict:
    """images: (media_type, data) pairs, e.g. screenshots of the 雅思哥 review page."""
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": mt,
                                     "data": base64.b64encode(data).decode()}}
        for mt, data in images
    ]
    content.append({"type": "text", "text": f"科目：{SKILL_ZH[skill]}\n\n{text or '（內容在截圖裡）'}"})
    try:
        response = _get_client().beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
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
    result = json.loads(texts[-1])
    if skill == "writing":
        result["question_count"], result["correct_count"] = 1, 0
    result["question_count"] = max(0, int(result["question_count"]))
    result["correct_count"] = max(0, min(int(result["correct_count"]), result["question_count"]))
    return result
