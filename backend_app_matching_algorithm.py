import itertools
from typing import List, Dict, Any

# --- 1. グループ全体の相性スコア計算関数 ---

def calculate_same_type_score(group: List[Dict[str, Any]]) -> int:
    """
    【同族重視】主要タイプの一致度 ＋ 軸スコアの近さで採点
    """
    types = [m["primary_type"] for m in group]
    first_type = types[0]
    
    # 4人全員が同じタイプでなければ不適合 (スコア0)
    if not all(t == first_type for t in types):
        return 0
    
    score = 100
    # 軸スコア (外向性 E, 成果 A) のブレ（標準偏差）が少ないほど高評価
    e_scores = [m["extraversion_score"] for m in group]
    a_scores = [m["achievement_score"] for m in group]
    
    # 軸スコアの最大差分をマイナス評価
    diff_e = max(e_scores) - min(e_scores)
    diff_a = max(a_scores) - min(a_scores)
    
    score -= (diff_e + diff_a) * 5
    return max(score, 1)


def calculate_balance_score(group: List[Dict[str, Any]]) -> int:
    """
    【バランス重視】4タイプの分散度（多様性）で採点
    """
    type_counts = {
        "chimpanzee": 0,
        "bonobo": 0,
        "gorilla": 0,
        "orangutan": 0
    }
    for m in group:
        type_counts[m["primary_type"]] += 1

    unique_types_count = sum(1 for count in type_counts.values() if count > 0)
    score = 0

    # 1. タイプの多様性ボーナス
    if unique_types_count == 4:
        score += 100  # 全種類揃う「黄金比」
    elif unique_types_count == 3:
        score += 70
    elif unique_types_count == 2:
        score += 40
    else:
        score += 10   # 全員同タイプはバランスマッチとしては低評価

    # 2. 偏りペナルティ (同タイプ3人以上は不協和音リスク)
    if type_counts["chimpanzee"] >= 3:
        score -= 40
    if type_counts["orangutan"] >= 3:
        score -= 40

    # 3. 潤滑油（ボノボ / ゴリラ）の存在ボーナス
    if type_counts["bonobo"] >= 1 or type_counts["gorilla"] >= 1:
        score += 20

    return max(score, 0)


# --- 2. メインのマッチング自動生成ロジック ---

def generate_matches(applications: List[Dict[str, Any]], match_mode: str = "BALANCE") -> List[Dict[str, Any]]:
    """
    未マッチングの応募一覧から、性別バランス（男性2:女性2）を満たす最高スコアの4人組を作る
    """
    males = [a for a in applications if a["gender"] == "male"]
    females = [a for a in applications if a["gender"] == "female"]
    
    matched_groups = []
    used_app_ids = set()

    # 男性2名・女性2名の組み合わせ総当たりペアを生成
    male_pairs = list(itertools.combinations(males, 2))
    female_pairs = list(itertools.combinations(females, 2))

    possible_groups = []

    # 全組み合わせの評価スコアを事前計算
    for m_pair in male_pairs:
        for f_pair in female_pairs:
            candidate_group = list(m_pair) + list(f_pair)
            
            # スコア計算
            if match_mode == "SAME_TYPE":
                score = calculate_same_type_score(candidate_group)
            else:
                score = calculate_balance_score(candidate_group)
                
            if score > 0:
                possible_groups.append({
                    "score": score,
                    "members": candidate_group,
                    "app_ids": [m["app_id"] for m in candidate_group]
                })

    # スコアが高い順にソート（グリーディ選択）
    possible_groups.sort(key=lambda x: x["score"], reverse=True)

    # 被りなくグループを確定させる
    for group in possible_groups:
        # メンバーの誰かが既に他のグループに割り振られていないかチェック
        if any(app_id in used_app_ids for app_id in group["app_ids"]):
            continue
        
        # マッチング成立
        matched_groups.append(group)
        for app_id in group["app_ids"]:
            used_app_ids.add(app_id)

    return matched_groups


# --- 3. 動作確認用のダミーデータテスト ---

if __name__ == "__main__":
    # テスト用の応募者ダミーデータ (8名)
    sample_applications = [
        {"app_id": "app_1", "name": "A男", "gender": "male", "primary_type": "chimpanzee", "extraversion_score": 5, "achievement_score": 5},
        {"app_id": "app_2", "name": "B男", "gender": "male", "primary_type": "bonobo", "extraversion_score": 4, "achievement_score": 2},
        {"app_id": "app_3", "name": "C男", "gender": "male", "primary_type": "gorilla", "extraversion_score": 1, "achievement_score": 2},
        {"app_id": "app_4", "name": "D男", "gender": "male", "primary_type": "orangutan", "extraversion_score": 1, "achievement_score": 5},
        
        {"app_id": "app_5", "name": "E女", "gender": "female", "primary_type": "chimpanzee", "extraversion_score": 6, "achievement_score": 4},
        {"app_id": "app_6", "name": "F女", "gender": "female", "primary_type": "bonobo", "extraversion_score": 5, "achievement_score": 1},
        {"app_id": "app_7", "name": "G女", "gender": "female", "primary_type": "gorilla", "extraversion_score": 2, "achievement_score": 1},
        {"app_id": "app_8", "name": "H女", "gender": "female", "primary_type": "orangutan", "extraversion_score": 0, "achievement_score": 4},
    ]

    print("=== 【バランス重視】マッチング実行結果 ===")
    results = generate_matches(sample_applications, match_mode="BALANCE")
    for idx, g in enumerate(results, 1):
        member_names = [m["name"] + f"({m['primary_type']})" for m in g["members"]]
        print(f"グループ {idx} [スコア: {g['score']}点]: {', '.join(member_names)}")
