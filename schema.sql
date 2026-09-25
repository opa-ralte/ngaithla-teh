-- schema.sql
-- Compatible with both MariaDB (Linux) and MySQL (Windows).
-- Run this against an empty database, e.g.:
--   mysql -u root -p your_db_name < schema.sql        (Windows/MySQL)
--   mariadb -u root -p your_db_name < schema.sql       (Linux/MariaDB)

CREATE TABLE IF NOT EXISTS users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(50)  NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS songs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    uploader_id     INT          NOT NULL,
    title           VARCHAR(150) NOT NULL,
    artist          VARCHAR(150) NOT NULL,
    filepath        VARCHAR(255) NOT NULL,
    uploaded_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploader_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ratings (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    song_id         INT          NOT NULL,
    user_id         INT          NOT NULL,
    stars           TINYINT      NOT NULL CHECK (stars BETWEEN 1 AND 5),
    review_text     TEXT,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY unique_rating_per_user_per_song (song_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Helpful view: average rating + review count per song
CREATE OR REPLACE VIEW song_ratings_summary AS
SELECT
    s.id AS song_id,
    s.title,
    s.artist,
    COALESCE(AVG(r.stars), 0) AS avg_rating,
    COUNT(r.id) AS rating_count
FROM songs s
LEFT JOIN ratings r ON s.id = r.song_id
GROUP BY s.id, s.title, s.artist;
