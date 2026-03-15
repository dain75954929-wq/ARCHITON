-- ARCHITON user tracking schema
-- This file is the SQL source of truth for tracking DB initialization.

CREATE TABLE IF NOT EXISTS user_credentials (
    user_id TEXT PRIMARY KEY,
    password TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS liked_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    project_id TEXT,
    image_id INTEGER,
    project_name TEXT,
    url TEXT,
    architect TEXT,
    location_country TEXT,
    program TEXT,
    year TEXT,
    mood TEXT,
    material TEXT,
    liked_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_liked_projects_user_image
ON liked_projects(user_id, project_id, image_id);
