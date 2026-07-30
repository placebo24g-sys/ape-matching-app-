from typing import List, Dict, Any

# --- 1. グループのタイプ特徴分析ロジック ---

def analyze_group_personality(group_members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    4人のタイプ構成・軸スコアから、グループ全体の「雰囲気・ニーズ」を判定する
    """
    type_counts = {
        "chimpanzee": 0,
        "bonobo": 0,
        "gorilla": 0,
        "orangutan": 0
    }
    for m in group_members:
        type_counts[m["primary_type"]] += 1

    unique_types = sum(1 for count in type_counts.values() if count > 0)
    
    # グループパターンの判定
    group_pattern = "STANDARD"
    
    if unique_types == 4:
        group_pattern = "GOLDEN_BALANCE"  # 4タイプ揃った黄金比
    elif max(type_counts.values()) >= 3:
        group_pattern = "SAME_TYPE_DOMINANT"  # 特定タイプが3人以上の同族型
    elif type_counts["chimpanzee"] + type_counts["bonobo"] >= 3:
        group_pattern = "EXTROVERT_ACTIVE"  # 感情表現・外向派メイン (チンパン＋ボノボ)
    elif type_counts["gorilla"] + type_counts["orangutan"] >= 3:
        group_pattern = "INTROVERT_CALM"    # 落ち着き・内向派メイン (ゴリラ＋オラン)
    elif type_counts["chimpanzee"] + type_counts["orangutan"] >= 3:
        group_pattern = "ACHIEVEMENT_LOGIC"  # 成果・ロジック志向 (チンパン＋オラン)
    elif type_counts["bonobo"] + type_counts["gorilla"] >= 3:
        group_pattern = "HARMONY_EMPATHY"    # 調和・共感志向 (ボノボ＋ゴリラ)

    return {
        "pattern": group_pattern,
        "counts": type_counts,
        "dominant_type": max(type_counts, key=type_counts.get)
    }


# --- 2. 店舗・コース提案エンジン ---

def recommend_shop_and_course(group_members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    分析結果に基づいて、最適な店舗条件・コース・選定理由を生成する
    """
    analysis = analyze_group_personality(group_members)
    pattern = analysis["pattern"]
    counts = analysis["counts"]
    dominant = analysis["dominant_type"]

    # デフォルト設定
    recommendation = {
        "category": "ネオ居酒屋 / カジュアルイタリアン",
        "seat_type": "テーブル席 / ややゆったりめの席",
        "course_style": "定番飲み放題付きコース (4,500円前後)",
        "volume": "標準",
        "key_features": ["会話がしやすい", "メニューの種類が豊富"],
        "reason": "多種多様なメンバーがバランスよく会話を楽しめるバランス型の選定です。"
    }

    # パターン1: 4タイプ揃った【黄金比グループ】
    if pattern == "GOLDEN_BALANCE":
        recommendation = {
            "category": "エンタメ性のあるバル / トレンド系居酒屋",
            "seat_type": "BOX席 / カウンターL字席（全員の顔が見えやすい席）",
            "course_style": "名物料理＋シェア系創作料理コース（飲み放題付 5,000円）",
            "volume": "中〜多め",
            "key_features": ["映えメニューあり", "個性が活きる賑やかさ", "ドリンクの種類が豊富"],
            "reason": "4タイプの多様性が生きる刺激的で話題に困らないトレンド感のあるお店がベストマッチです！"
        }

    # パターン2: 【同族重視グループ】（特定タイプが3人以上）
    elif pattern == "SAME_TYPE_DOMINANT":
        if dominant == "chimpanzee":
            recommendation = {
                "category": "活気ある肉バル / 賑やかなイタリアン",
                "seat_type": "オープンエリアのテーブル席",
                "course_style": "ガッツリ肉盛り＋ビール充実コース（5,500円）",
                "volume": "多め（満足感重視）",
                "key_features": ["盛り上がる雰囲気", "肉料理メイン"],
                "reason": "勝ち気で情熱的なチンパンジー多め！テンションが高まる賑やかな雰囲気と満足感のある肉料理が最適です。"
            }
        elif dominant == "gorilla":
            recommendation = {
                "category": "落ち着いた個室和食 / 伝統的な居酒屋",
                "seat_type": "完全個室（掘りごたつ）",
                "course_style": "銘々皿で提供される和食会席コース（5,000円）",
                "volume": "標準（取り分け不要）",
                "key_features": ["静かな空間", "取り分けの手間なし", "礼儀・マナーが守りやすい"],
                "reason": "気配り上手なゴリラ多め！気を使わずに済む『取り分け不要のコース』と静かな個室で安心感を提供します。"
            }
        elif dominant == "bonobo":
            recommendation = {
                "category": "お洒落なカフェダイニング / アジアンバル",
                "seat_type": "ソファ席（距離が近い席）",
                "course_style": "デザート付き・写真映えシェアコース（4,500円）",
                "volume": "標準（見た目重視）",
                "key_features": ["共感・会話が弾む", "可愛いドリンク・デザート"],
                "reason": "感情豊かで共感度高めなボノボグループ！距離が縮まるソファ席と会話のきっかけになる映え料理がぴったりです。"
            }
        elif dominant == "orangutan":
            recommendation = {
                "category": "こだわりのクラフトビールバー / 隠れ家ビストロ",
                "seat_type": "落ち着いたテーブル席（静かめ）",
                "course_style": "料理ペアリング＋こだわりアラカルト風コース（6,000円）",
                "volume": "質重視",
                "key_features": ["料理・酒の解説あり", "ガヤガヤしていない", "マイペースに楽しめる"],
                "reason": "理知的で職人肌のオランウータン多め！BGMが静かで食へのこだわり・ウンチクが楽しめる隠れ家がマッチします。"
            }

    # パターン3: 【内向・落ち着きグループ】（ゴリラ＋オランウータン）
    elif pattern == "INTROVERT_CALM":
        recommendation = {
            "category": "静かな和風個室居酒屋 / 落ち着いた焼き鳥店",
            "seat_type": "静かな半個室 / 落ち着いたテーブル席",
            "course_style": "季節の旬素材コース（飲み放題付 5,000円）",
            "volume": "標準",
            "key_features": ["騒がしくない", "じっくり話せる", "席間隔が広い"],
            "reason": "じっくり深く話したいおだやかグループ。周囲の騒音に邪魔されない落ち着いた個室空間を用意します。"
        }

    # パターン4: 【外向・盛り上がりグループ】（チンパンジー＋ボノボ）
    elif pattern == "EXTROVERT_ACTIVE":
        recommendation = {
            "category": "トレンドの韓国料理 / エスニックバル",
            "seat_type": "賑やかなテーブル席",
            "course_style": "ワイワイつつくサムギョプサル・鍋コース（4,500円）",
            "volume": "多め",
            "key_features": ["体感型メニュー", "賑やかなBGM", "飲み放題の種類が豊富"],
            "reason": "明るくエネルギー溢れるグループ！みんなで囲んで盛り上がれる体感型の料理とお酒が相性抜群です。"
        }

    return {
        "group_pattern": pattern,
        "analysis": analysis,
        "recommendation": recommendation
    }


# --- 3. 動作確認テスト ---

if __name__ == "__main__":
    # テスト用グループ（例: ゴリラ多めのグループ）
    gorilla_group = [
        {"name": "A男", "primary_type": "gorilla"},
        {"name": "B男", "primary_type": "gorilla"},
        {"name": "C女", "primary_type": "gorilla"},
        {"name": "D女", "primary_type": "bonobo"},
    ]

    result = recommend_shop_and_course(gorilla_group)
    print("=== レコメンド実行結果 ===")
    print(f"グループパターン: {result['group_pattern']}")
    print(f"おすすめカテゴリ: {result['recommendation']['category']}")
    print(f"推奨席タイプ:     {result['recommendation']['seat_type']}")
    print(f"おすすめコース:   {result['recommendation']['course_style']}")
    print(f"選定理由:         {result['recommendation']['reason']}")