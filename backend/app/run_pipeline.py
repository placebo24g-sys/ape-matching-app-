# 1. ２つのモジュールから関数をインポート
from matching_algorithm import generate_matches
from shop_recommender import recommend_shop_and_course

def process_matching_and_recommendation(applications, match_mode="BALANCE"):
    """
    応募データからマッチングを行い、成立した各グループに対して最適なお店をレコメンドするパイプライン
    """
    # Step 1: マッチングを実行してグループを生成
    matched_groups = generate_matches(applications, match_mode=match_mode)
    
    pipeline_results = []

    # Step 2: 成立したグループごとに店舗レコメンドを実行
    for idx, group in enumerate(matched_groups, 1):
        members = group["members"]
        
        # 店舗レコメンドエンジンを呼び出し
        shop_proposal = recommend_shop_and_course(members)
        
        # マッチング結果と店舗提案をセットにする
        combined_result = {
            "group_id": f"group_{idx}",
            "match_score": group["score"],
            "members": [
                {"name": m["name"], "gender": m["gender"], "type": m["primary_type"]} 
                for m in members
            ],
            "recommended_shop": shop_proposal["recommendation"]
        }
        pipeline_results.append(combined_result)

    return pipeline_results


# --- 動作確認用テスト実行 ---
if __name__ == "__main__":
    # 応募ダミーデータ (8名)
    sample_applications = [
        {"app_id": "app_1", "name": "A男", "gender": "male", "primary_type": "gorilla", "extraversion_score": 1, "achievement_score": 2},
        {"app_id": "app_2", "name": "B男", "gender": "male", "primary_type": "gorilla", "extraversion_score": 2, "achievement_score": 1},
        {"app_id": "app_3", "name": "C男", "gender": "male", "primary_type": "orangutan", "extraversion_score": 0, "achievement_score": 4},
        {"app_id": "app_4", "name": "D男", "gender": "male", "primary_type": "chimpanzee", "extraversion_score": 5, "achievement_score": 5},
        
        {"app_id": "app_5", "name": "E女", "gender": "female", "primary_type": "gorilla", "extraversion_score": 1, "achievement_score": 1},
        {"app_id": "app_6", "name": "F女", "gender": "female", "primary_type": "bonobo", "extraversion_score": 4, "achievement_score": 2},
        {"app_id": "app_7", "name": "G女", "gender": "female", "primary_type": "orangutan", "extraversion_score": 1, "achievement_score": 5},
        {"app_id": "app_8", "name": "H女", "gender": "female", "primary_type": "chimpanzee", "extraversion_score": 6, "achievement_score": 4},
    ]

    # パイプライン実行
    results = process_matching_and_recommendation(sample_applications, match_mode="BALANCE")

    # 結果の表示
    for res in results:
        print(f"\n==================== 【{res['group_id']} (相性スコア: {res['match_score']}点)】 ====================")
        print("■ メンバー:")
        for m in res["members"]:
            print(f"  - {m['name']} ({m['gender']}) : {m['type']}")
            
        rec = res["recommended_shop"]
        print("\n■ おすすめの店舗設定:")
        print(f"  ・カテゴリ: {rec['category']}")
        print(f"  ・希望席:   {rec['seat_type']}")
        print(f"  ・コース:   {rec['course_style']}")
        print(f"  ・選定理由: {rec['reason']}")