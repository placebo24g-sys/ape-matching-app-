-- 1. ユーザー基本情報テーブル
CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    gender VARCHAR(10) NOT NULL,
    birth_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 類人猿診断結果テーブル
CREATE TABLE ape_profiles (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    primary_type VARCHAR(20) NOT NULL,
    score_chimpanzee INT NOT NULL,
    score_bonobo INT NOT NULL,
    score_gorilla INT NOT NULL,
    score_orangutan INT NOT NULL,
    extraversion_score INT NOT NULL,
    achievement_score INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. 成立グループテーブル
CREATE TABLE match_groups (
    id VARCHAR(36) PRIMARY KEY,
    match_mode VARCHAR(20) NOT NULL, -- 'SAME_TYPE' または 'BALANCE'
    score INT NOT NULL,
    event_date DATE NOT NULL,
    area VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'formed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. 応募エントリーテーブル
CREATE TABLE applications (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    ape_profile_id VARCHAR(36) NOT NULL REFERENCES ape_profiles(id),
    event_date DATE NOT NULL,
    preferred_area VARCHAR(50) NOT NULL,
    match_mode VARCHAR(20) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    group_id VARCHAR(36) REFERENCES match_groups(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. 店舗予約テーブル
CREATE TABLE reservations (
    id VARCHAR(36) PRIMARY KEY,
    group_id VARCHAR(36) UNIQUE NOT NULL REFERENCES match_groups(id),
    shop_id VARCHAR(50) NOT NULL,
    shop_name VARCHAR(100) NOT NULL,
    course_name VARCHAR(100),
    reserved_at TIMESTAMP NOT NULL,
    total_price INT,
    status VARCHAR(20) DEFAULT 'confirmed'
);
