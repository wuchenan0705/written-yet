"""IELTS Academic Writing quick reference: task types, structures and linking words.

Plain data so both the web page and the LINE bot can render it.
"""

OVERVIEW = {
    "tasks": [
        {"name": "Task 1", "time": "建議 20 分鐘", "words": "至少 150 字", "weight": "佔寫作分數約 1/3",
         "what": "描述圖表、流程或地圖，只寫看到的資料，不給意見、不猜原因。"},
        {"name": "Task 2", "time": "建議 40 分鐘", "words": "至少 250 字", "weight": "佔寫作分數約 2/3",
         "what": "針對一個議題寫議論文，要完整回答題目的每個部分，立場從頭到尾一致。"},
    ],
    "criteria": [
        ("Task Achievement / Task Response", "有沒有完整回答題目。Task 1 要有 overview 和重點數據；Task 2 要回答每個問題、立場清楚、論點有展開。"),
        ("Coherence & Cohesion", "段落分得好、每段一個中心、連接詞用得自然（太多太機械反而扣分）、代名詞指涉清楚。"),
        ("Lexical Resource", "用字精準多變、會換句話說、搭配詞（collocation）正確、拼字正確。"),
        ("Grammatical Range & Accuracy", "句型多樣（複句、關係子句、條件句、被動）且錯誤少。"),
    ],
    "note": "四項各佔該篇 25%。Task 2 的分數權重是 Task 1 的兩倍，時間不夠時優先把 Task 2 寫完整。",
}

TASK1_TYPES = [
    {
        "id": "line", "name": "折線圖 Line graph", "focus": "隨時間的變化趨勢",
        "structure": ["改寫題目（不要照抄）", "Overview：整體趨勢＋最高/最低或最大變化", "Body 1：一組主要趨勢與數據", "Body 2：另一組趨勢或比較"],
        "tips": ["先找「整體上升/下降」和「誰最高、誰變化最大」寫成 overview。",
                 "注意起點、終點、最高點、交叉點。",
                 "時態跟著圖表的時間走；有預測年份用 is expected / is predicted to。"],
        "example": "Overall, the number of visitors to all three museums rose over the period, with the Science Museum remaining the most popular throughout.",
    },
    {
        "id": "bar", "name": "長條圖 Bar chart", "focus": "類別之間的比較（有時也含時間）",
        "structure": ["改寫題目", "Overview：最大/最小的類別、明顯的差異或共同模式", "Body 1：較高的一群", "Body 2：較低的一群或對比"],
        "tips": ["先分組再寫，不要一根一根照順序念。",
                 "如果有時間軸，就同時用比較和趨勢的語言。"],
        "example": "Overall, men spent considerably more time on sport than women in every age group, and participation declined with age for both sexes.",
    },
    {
        "id": "pie", "name": "圓餅圖 Pie chart", "focus": "各部分佔整體的比例",
        "structure": ["改寫題目", "Overview：最大的部分、最小的部分、兩年間最大的變化", "Body 1：最大的幾塊", "Body 2：其餘部分或年份間的變化"],
        "tips": ["多用比例說法：a quarter, just under a third, the majority。",
                 "兩個圓餅圖比較時，重點是哪一塊變大、哪一塊變小。"],
        "example": "Overall, housing accounted for the largest share of household spending in both years, while the proportion spent on food fell noticeably.",
    },
    {
        "id": "table", "name": "表格 Table", "focus": "很多數字，需要自己挑重點",
        "structure": ["改寫題目", "Overview：最高/最低的項目、明顯模式", "Body 1：依類別或年份挑重點", "Body 2：其餘對比"],
        "tips": ["不要每格都寫，挑極端值和明顯差異。", "數字可以四捨五入搭配 approximately / just over。"],
        "example": "Overall, Japan had the highest proportion of elderly residents in all three years, whereas the figures for Brazil remained the lowest.",
    },
    {
        "id": "mixed", "name": "混合圖 Multiple charts", "focus": "兩種圖表（例如折線圖＋表格）",
        "structure": ["改寫題目（兩張圖都要提）", "Overview：兩張圖各一個重點", "Body 1：圖一", "Body 2：圖二（能連結就連結）"],
        "tips": ["一張圖一段最清楚。", "overview 一定要兩張圖都講到。"],
        "example": "Overall, car ownership increased steadily, while the table shows that most of these vehicles were used for commuting.",
    },
    {
        "id": "process", "name": "流程圖 Process diagram", "focus": "步驟順序（自然循環或人造製程）",
        "structure": ["改寫題目", "Overview：總共幾個步驟、從哪裡開始到哪裡結束、是否循環", "Body 1：前半段步驟", "Body 2：後半段步驟"],
        "tips": ["人造製程多用被動語態：The beans are roasted and then ground.",
                 "用順序詞串連：First, Next, After that, Once..., Finally。",
                 "每個步驟都要提到，不要漏。"],
        "example": "Overall, there are eight stages in the production of glass bottles, beginning with the collection of raw materials and ending with distribution to shops.",
    },
    {
        "id": "map", "name": "地圖 Map", "focus": "同一地點不同時間的變化",
        "structure": ["改寫題目", "Overview：整體最大的改變（例如變得更都市化）", "Body 1：某區域或某時期的變化", "Body 2：另一區域或時期"],
        "tips": ["方位與位置：to the north of, next to, opposite, in the centre。",
                 "變化動詞多用被動：was demolished / was replaced by / was converted into / was extended。"],
        "example": "Overall, the village became far more developed, with farmland largely replaced by housing and new roads.",
    },
]

TASK1_LANGUAGE = [
    {"title": "上升", "items": ["rise / increase / grow / climb", "rise sharply / soar / surge / rocket（大幅）", "a significant rise in ...", "an upward trend"]},
    {"title": "下降", "items": ["fall / decrease / decline / drop", "plummet / plunge（暴跌）", "dip（小跌）", "a steady decline in ...", "a downward trend"]},
    {"title": "持平與波動", "items": ["remain stable / stay constant / remain unchanged", "level off / plateau（在...後趨於平穩）", "fluctuate (between X and Y)", "peak at ... / reach a peak of ...", "hit a low of / bottom out at ..."]},
    {"title": "程度副詞", "items": ["dramatically / sharply / significantly（大）", "considerably / substantially（相當大）", "steadily / gradually（穩定）", "slightly / marginally（小）"]},
    {"title": "約略數字", "items": ["approximately / roughly / around / about", "just over / just under / nearly / almost", "well over / well below"]},
    {"title": "比例", "items": ["a quarter / a third / half / three quarters", "one in five", "the majority of / a minority of", "the largest share / proportion of"]},
    {"title": "比較", "items": ["twice as many / much as", "X was higher than Y", "the highest / the lowest", "compared with / in comparison with", "whereas / while（連接兩個子句）", "by contrast / in contrast（句首加逗號）"]},
    {"title": "時間", "items": ["over the period / between 1990 and 2010", "from 1990 to 2010", "by 2020（到2020年為止）", "in the following decade", "is projected / predicted to ..."]},
]

TASK2_TYPES = [
    {
        "id": "opinion", "name": "同意/不同意 Opinion",
        "keywords": ["To what extent do you agree or disagree?", "Do you agree or disagree?"],
        "structure": ["引言：改寫題目＋清楚立場（完全同意、完全不同意或部分同意）", "Body 1：支持立場的理由一＋例子", "Body 2：理由二（或讓步後反駁）", "結論：重申立場"],
        "tips": ["立場要在引言就說清楚，結論不能改變。", "「部分同意」要說明同意哪部分、不同意哪部分。"],
        "thesis": "I completely agree that ..., because ... and ...",
    },
    {
        "id": "discussion", "name": "雙邊討論 Discussion",
        "keywords": ["Discuss both views and give your own opinion."],
        "structure": ["引言：介紹兩種觀點＋你的立場", "Body 1：觀點 A 的理由", "Body 2：觀點 B 的理由（通常放你支持的一方）", "結論：總結＋你的立場"],
        "tips": ["兩邊都要講到，而且都要展開。", "題目有 give your own opinion 就一定要表態。"],
        "thesis": "While some argue that ..., I believe that ...",
    },
    {
        "id": "adv", "name": "優缺點 Advantages & Disadvantages",
        "keywords": ["Do the advantages outweigh the disadvantages?", "What are the advantages and disadvantages?"],
        "structure": ["引言：改寫題目（問 outweigh 要表態）", "Body 1：優點", "Body 2：缺點", "結論：哪一邊比較重要"],
        "tips": ["問 outweigh 是要你判斷哪邊比較多/重要，不能只列出來。", "只問 what are... 則兩邊平衡討論即可。"],
        "thesis": "Although ... has some drawbacks, I believe the benefits are far greater.",
    },
    {
        "id": "problem", "name": "問題/原因＋解決 Problem / Cause & Solution",
        "keywords": ["What are the causes of this problem? What solutions can you suggest?", "What problems does this cause, and how can they be solved?"],
        "structure": ["引言：改寫題目＋預告會談的原因/問題和解決方法", "Body 1：原因或問題（1–2 個，要解釋）", "Body 2：對應的解決方法", "結論：總結"],
        "tips": ["解決方法最好對應前面講的原因。", "看清楚題目問 causes 還是 problems / effects。"],
        "thesis": "This essay will examine the main causes of ... and suggest some practical solutions.",
    },
    {
        "id": "development", "name": "正面或負面發展 Positive / Negative development",
        "keywords": ["Is this a positive or negative development?"],
        "structure": ["引言：改寫＋表態（正面/負面/大致正面）", "Body 1：主要理由", "Body 2：第二個理由或讓步後反駁", "結論：重申"],
        "tips": ["本質上是 opinion 題，要明確判斷。"],
        "thesis": "In my view, this is largely a positive development because ...",
    },
    {
        "id": "two-part", "name": "雙問題 Two-part / Direct questions",
        "keywords": ["Why is this the case? Do you think this is a good thing?", "What are the reasons? What can be done?"],
        "structure": ["引言：改寫＋簡短回答兩個問題", "Body 1：回答第一題", "Body 2：回答第二題", "結論：總結兩個答案"],
        "tips": ["兩題都要答，篇幅大致平均。", "每段第一句直接回答該段的問題。"],
        "thesis": "This trend is mainly due to ..., and I believe it is a positive change.",
    },
]

# Each connector: (phrase, usage note, example). Usage notes cover the grammar that
# actually costs marks: sentence adverb vs. conjunction vs. preposition.
CONNECTORS = [
    {"id": "add", "title": "補充、遞進", "items": [
        ("Furthermore, / Moreover,", "句首副詞，後加逗號；比 also 正式", "Moreover, public transport reduces traffic congestion."),
        ("In addition, / Additionally,", "句首副詞＋逗號", "In addition, cycling improves people's health."),
        ("In addition to + N / V-ing", "介系詞，後接名詞或動名詞", "In addition to saving money, it saves time."),
        ("not only ... but also ...", "放在主詞前要倒裝：Not only does it...", "It not only saves time but also reduces stress."),
        ("Also,", "可用，但別每段都用；放句中更自然", "Online courses are also cheaper."),
    ]},
    {"id": "contrast", "title": "對比、轉折", "items": [
        ("However, / Nevertheless,", "句首副詞＋逗號；不能直接連接兩個子句", "Cars are convenient. However, they cause pollution."),
        ("On the other hand,", "引出同一議題的另一面，不是單純補充", "On the other hand, remote work can feel isolating."),
        ("In contrast, / By contrast,", "對比兩件事物的差異", "By contrast, sales in Europe fell."),
        ("whereas / while", "連接詞，連接兩個對比子句，前面常加逗號", "Men preferred football, whereas women preferred tennis."),
        ("although / even though + S + V", "連接詞；不能再加 but", "Although it is expensive, many people buy it."),
        ("despite / in spite of + N / V-ing", "介系詞；沒有 despite of", "Despite the cost, many people buy it."),
        ("Conversely,", "引出相反情況（較正式）", "Conversely, a lack of exercise increases health risks."),
    ]},
    {"id": "cause", "title": "原因", "items": [
        ("because / since / as + S + V", "連接詞，後接子句", "Many people move to cities because jobs are easier to find."),
        ("because of / due to / owing to + N", "介系詞片語，後接名詞", "Due to rising rents, many young people live with their parents."),
        ("This is because ...", "解釋上一句的原因，很好用", "This is because employers value experience."),
        ("One reason for this is that ...", "引出原因的主題句", "One reason for this is that housing is unaffordable."),
    ]},
    {"id": "result", "title": "結果", "items": [
        ("Therefore, / Consequently, / As a result,", "句首副詞＋逗號", "As a result, air quality has improved."),
        ("Thus, / Hence,", "較正式；hence 也可接名詞片語", "Hence the need for stricter laws."),
        ("so + S + V", "連接詞，口語一點，前面加逗號", "Prices rose, so demand fell."),
        ("..., leading to / resulting in + N", "分詞片語，把結果接在句尾，讓句子更進階", "Factories closed, resulting in high unemployment."),
        ("This means that ...", "說明影響", "This means that fewer people can afford a home."),
    ]},
    {"id": "example", "title": "舉例", "items": [
        ("For example, / For instance,", "句首＋逗號，後接完整句子", "For example, Singapore charges drivers to enter the city centre."),
        ("such as + N", "後接名詞，不能接完整句子", "Sports such as swimming are low-impact."),
        ("A good example of this is ...", "引出具體例子", "A good example of this is Finland's education system."),
        ("namely", "列出前面說的具體項目", "Two subjects, namely maths and science, were affected."),
    ]},
    {"id": "concession", "title": "讓步", "items": [
        ("Admittedly, / It is true that ..., but ...", "先承認對方的論點，再反駁", "It is true that technology isolates people, but it also connects them."),
        ("While it may be true that ..., ...", "讓步子句", "While it may be true that zoos protect animals, many are poorly run."),
        ("Even so,", "即使如此", "Even so, the benefits outweigh the costs."),
    ]},
    {"id": "emphasis", "title": "強調", "items": [
        ("Indeed, / In fact,", "加強前一句", "In fact, most accidents happen near home."),
        ("particularly / especially", "副詞，放在要強調的成分前", "This is especially true in rural areas."),
        ("Clearly, / Undoubtedly,", "表示明顯（不要過度使用）", "Clearly, education plays a key role."),
    ]},
    {"id": "sequence", "title": "順序（流程圖必備）", "items": [
        ("First, / Firstly, / To begin with,", "第一步", "First, the raw materials are collected."),
        ("Next, / Then, / After that, / Subsequently,", "接下來", "Subsequently, the mixture is heated."),
        ("Once / After + S + V", "連接詞，前一步完成後", "Once the leaves are dried, they are packed."),
        ("Meanwhile,", "同時", "Meanwhile, the waste is recycled."),
        ("Finally,", "最後一步", "Finally, the bottles are delivered to shops."),
    ]},
    {"id": "condition", "title": "條件", "items": [
        ("If + S + V", "條件子句", "If governments invested more, the situation would improve."),
        ("unless + S + V", "除非（= if not）", "Unless action is taken, the problem will worsen."),
        ("provided that / as long as", "只要", "Remote work is effective provided that teams communicate well."),
        ("Otherwise,", "否則（句首）", "Otherwise, prices will continue to rise."),
    ]},
    {"id": "clarify", "title": "換句話說", "items": [
        ("In other words,", "換個說法解釋", "In other words, people are working longer hours."),
        ("That is to say,", "也就是說（較正式）", "That is to say, the policy failed."),
    ]},
    {"id": "opinion", "title": "表達立場", "items": [
        ("In my view, / In my opinion,", "Task 2 用；Task 1 不能給意見", "In my view, this is a positive development."),
        ("I firmly believe that ...", "立場強烈", "I firmly believe that education should be free."),
        ("It seems to me that ...", "語氣較委婉", "It seems to me that both sides have valid points."),
    ]},
    {"id": "conclusion", "title": "結論 / Overview", "items": [
        ("In conclusion, / To conclude,", "Task 2 結論段開頭，全文只用一次", "In conclusion, I believe the benefits outweigh the drawbacks."),
        ("On balance,", "權衡兩邊後的結論", "On balance, the advantages are more significant."),
        ("Overall,", "Task 1 overview 最常用", "Overall, the number of tourists increased."),
        ("In summary,", "Task 1 結尾也可以；Task 2 用 in conclusion 更常見", "In summary, coal remained the main energy source."),
    ]},
]

CONNECTOR_PITFALLS = [
    ("Although ..., but ...", "although 和 but 只能留一個：Although it is cheap, it is slow."),
    ("Despite of ...", "沒有 despite of；用 despite + N 或 in spite of + N。"),
    ("Despite it is expensive, ...", "despite 後面不能接子句：Despite being expensive / Although it is expensive。"),
    ("..., however it is ...", "however 不能像 but 一樣直接連兩句：用句號或分號 → ...; however, it is ..."),
    ("On the other hand 當「而且」", "on the other hand 是另一面（對比），補充要用 moreover / in addition。"),
    ("每句都放連接詞", "過度、機械式的連接詞會被扣 Coherence & Cohesion；用代名詞 this / these 和自然的句子順序串連。"),
    ("In a nutshell / Last but not least", "太口語或太公式化，用 In conclusion / Finally 就好。"),
]

TEMPLATES = [
    {"title": "Task 1 開頭（改寫題目）", "items": [
        "The line graph illustrates changes in ... between 1990 and 2020.",
        "The bar chart compares ... in five countries in 2015.",
        "The diagram shows the process by which ... is produced.",
        "The maps illustrate how ... changed between 1995 and the present day.",
    ]},
    {"title": "Task 1 Overview", "items": [
        "Overall, it is clear that ... , while ...",
        "Overall, the most striking feature is that ...",
        "Overall, there are X stages in the process, beginning with ... and ending with ...",
    ]},
    {"title": "Task 2 開頭與立場", "items": [
        "It is often argued that ... . I completely agree / disagree with this view because ...",
        "Some people believe that ..., whereas others argue that ... . In my view, ...",
        "This essay will discuss both views before explaining why I believe ...",
    ]},
    {"title": "Task 2 主題句與展開", "items": [
        "The main reason why ... is that ...",
        "Another important factor is ...",
        "This is because ... . As a result, ...",
        "A clear example of this can be seen in ...",
    ]},
    {"title": "Task 2 結論", "items": [
        "In conclusion, although ..., I believe that ...",
        "In conclusion, ... is mainly caused by ..., and it could be tackled by ...",
    ]},
]

COMMON_MISTAKES = [
    "字數不夠（Task 1 < 150、Task 2 < 250）會直接扣分。",
    "Task 1 沒寫 overview，Task Achievement 很難超過 5 分。",
    "Task 1 寫了原因或個人意見（圖表沒給的資訊不要寫）。",
    "Task 1 把數字一個一個念出來，沒有比較和分組。",
    "Task 2 沒回答到題目的每一部分，或立場前後不一致。",
    "照抄題目句子：抄的字不算進字數，也看不出詞彙能力。",
    "用縮寫（don't, it's）和口語（a lot of, kids, stuff）；學術寫作要正式。",
    "整篇只有一段或段落沒有中心句。",
    "背太多模板句，內容空洞；考官看的是真正的論述。",
]

TIME_PLAN = [
    ("Task 1（20 分鐘）", "3 分鐘看圖找重點與 overview → 15 分鐘寫 → 2 分鐘檢查"),
    ("Task 2（40 分鐘）", "5 分鐘審題列大綱 → 30 分鐘寫 → 5 分鐘檢查"),
    ("建議順序", "先寫 Task 2 也可以，它分數權重較高。"),
]


def find_connector_group(query: str):
    """Match a LINE query like 對比 / contrast / 原因 to a connector group."""
    q = query.strip().lower()
    for g in CONNECTORS:
        if q and (q in g["title"].lower() or q == g["id"]):
            return g
    return None


def connector_text(group: dict) -> str:
    lines = [f"🔗 {group['title']}"]
    for phrase, note, example in group["items"]:
        lines.append(f"\n▪️ {phrase}\n{note}\n例：{example}")
    return "\n".join(lines)
