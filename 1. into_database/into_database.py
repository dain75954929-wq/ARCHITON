import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_JSON_PATH = BASE_DIR / "sj_processed_raw_database_v7.json"
DEFAULT_PREVIEW_PATH = BASE_DIR / "into_database_preview.csv"
DEFAULT_VECTOR_DB_FILE_PATH = BASE_DIR / "into_database"
DEFAULT_TABLE_NAME = "architecture_vectors"
DEFAULT_DB_NAME = "into_database"
DEFAULT_VIEW_NAME = "into_database"
DEFAULT_DB_PASSWORD = ""
DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def suppress_model_load_warnings() -> None:
    """Silence non-critical model-loading warnings from transformers."""
    try:
        from transformers import logging as transformers_logging

        transformers_logging.set_verbosity_error()
    except Exception:
        # If transformers logging cannot be configured, continue with defaults.
        pass


@dataclass
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    db_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load architecture JSON into PostgreSQL vector DB (pgvector)."
    )
    parser.add_argument("--json-path", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--table", type=str, default=DEFAULT_TABLE_NAME)
    parser.add_argument("--view-name", type=str, default=DEFAULT_VIEW_NAME)
    parser.add_argument("--db-name", type=str, default=DEFAULT_DB_NAME)
    parser.add_argument("--db-host", type=str, default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--db-user", type=str, default=os.getenv("PGUSER", "postgres"))
    parser.add_argument(
        "--db-password",
        type=str,
        default=os.getenv("PGPASSWORD", DEFAULT_DB_PASSWORD),
    )
    parser.add_argument("--embedding-model", type=str, default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--preview-size", type=int, default=20)
    parser.add_argument("--preview-path", type=Path, default=DEFAULT_PREVIEW_PATH)
    parser.add_argument(
        "--vector-db-file-path",
        type=Path,
        default=DEFAULT_VECTOR_DB_FILE_PATH,
    )
    return parser.parse_args()


def get_db_config(args: argparse.Namespace) -> DbConfig:
    return DbConfig(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=args.db_password,
        db_name=args.db_name,
    )


def read_json(json_path: Path) -> list[dict[str, Any]]:
    if not json_path.exists():
        raise SystemExit(f"JSON 파일을 찾을 수 없습니다: {json_path}")

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        for key in ("data", "items", "records", "results"):
            if key in data:
                data = data[key]
                break

    if not isinstance(data, list) or len(data) == 0:
        raise SystemExit("JSON이 비어 있거나 올바른 형식이 아닙니다. 배열(list) 형태여야 합니다.")

    required = {
        "url",
        "project_name",
        "architect",
        "location_country",
        "area",
        "program",
        "year",
        "mood",
        "material",
    }
    missing = required - set(data[0].keys())
    if missing:
        raise SystemExit(f"필수 필드가 없습니다: {sorted(missing)}")

    return data


def normalize_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def parse_images(images_value: Any) -> list[str]:
    if images_value is None:
        return []
    if isinstance(images_value, list):
        return [str(p).strip() for p in images_value if p and str(p).strip()]
    parts = [p.strip() for p in str(images_value).split("|")]
    return [p for p in parts if p]


def normalize_year(raw_year: Any) -> int | None:
    if raw_year is None:
        return None
    text = str(raw_year).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 4:
        return int(digits[:4])
    return None


def make_document(row: dict[str, Any]) -> str:
    axes = [
        f"project_name: {row['project_name']}",
        f"architect: {row['architect']}",
        f"location_country: {row['location_country']}",
        f"area: {row['area']}",
        f"program: {row['program']}",
        f"year: {row['year'] if row['year'] is not None else 'unknown'}",
        f"mood: {row['mood']}",
        f"material: {row['material']}",
        f"url: {row['url']}",
    ]
    return " | ".join(axes)


def normalize_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for record in records:
        url = normalize_text(record.get("url"), "")
        project_name = normalize_text(record.get("project_name"), "untitled_project")
        architect = normalize_text(record.get("architect"), "unknown")
        location_country = normalize_text(record.get("location_country"), "unknown")
        area = normalize_text(record.get("area"), "unknown")
        program = normalize_text(record.get("program"), "unknown")
        year = normalize_year(record.get("year"))
        mood = normalize_text(record.get("mood"), "unknown")
        material = normalize_text(record.get("material"), "unknown")

        if not url:
            synthetic_key = hashlib.sha1(project_name.encode("utf-8")).hexdigest()
            url = f"missing://{synthetic_key}"

        normalized = {
            "url": url,
            "project_name": project_name,
            "architect": architect,
            "location_country": location_country,
            "area": area,
            "program": program,
            "year": year,
            "mood": mood,
            "material": material,
        }
        normalized["document_text"] = make_document(normalized)
        normalized["record_key"] = hashlib.sha1(normalized["url"].encode("utf-8")).hexdigest()
        rows.append(normalized)

    return rows


def create_schema(conn: Any, table_name: str, view_name: str) -> None:
    create_sql = f"""
    CREATE EXTENSION IF NOT EXISTS vector;

    DROP VIEW IF EXISTS {view_name};
    DROP TABLE IF EXISTS {table_name};

    CREATE TABLE {table_name} (
        id BIGSERIAL PRIMARY KEY,
        record_key TEXT UNIQUE NOT NULL,
        url TEXT NOT NULL,
        project_name TEXT NOT NULL,
        architect TEXT,
        location_country TEXT,
        area TEXT,
        program TEXT,
        year INTEGER,
        mood TEXT,
        material TEXT,
        document_text TEXT NOT NULL,
        embedding vector(384) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX idx_{table_name}_project_name ON {table_name}(project_name);
    CREATE INDEX idx_{table_name}_year ON {table_name}(year);

    CREATE VIEW {view_name} AS
    SELECT
        id,
        url,
        project_name,
        architect,
        location_country,
        area,
        program,
        year,
        mood,
        material,
        document_text,
        embedding,
        updated_at
    FROM {table_name};
    """
    with conn.cursor() as cur:
        cur.execute(create_sql)
    conn.commit()


def to_vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"


def get_table_embedding_dimension(conn: Any, table_name: str) -> int | None:
    query = """
    SELECT format_type(a.atttypid, a.atttypmod)
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relname = %s
      AND a.attname = 'embedding'
      AND a.attnum > 0
      AND NOT a.attisdropped
    ORDER BY n.nspname = 'public' DESC
    LIMIT 1
    """

    with conn.cursor() as cur:
        cur.execute(query, (table_name,))
        row = cur.fetchone()

    if not row or not row[0]:
        return None

    type_text = str(row[0]).strip()
    if type_text.startswith("vector(") and type_text.endswith(")"):
        dim_text = type_text[7:-1]
        if dim_text.isdigit():
            return int(dim_text)
    return None


def get_table_row_count(conn: Any, table_name: str) -> int:
    query = f"SELECT COUNT(*) FROM {table_name}"
    with conn.cursor() as cur:
        cur.execute(query)
        row = cur.fetchone()
    return int(row[0]) if row else 0


def export_vector_db_file(conn: Any, table_name: str, out_path: Path) -> None:
    query = f"""
    SELECT
        id,
        record_key,
        url,
        project_name,
        architect,
        location_country,
        area,
        program,
        year,
        mood,
        material,
        document_text,
        embedding::text AS embedding,
        created_at,
        updated_at
    FROM {table_name}
    ORDER BY id
    """
    with conn.cursor() as cur:
        cur.execute(query)
        columns = [desc[0] for desc in cur.description]
        data = cur.fetchall()

    df = pd.DataFrame(data, columns=columns)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")


def upsert_rows(
    conn: Any,
    table_name: str,
    rows: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    sql = f"""
    INSERT INTO {table_name} (
        record_key, url, project_name, architect, location_country,
        area, program, year, mood, material, document_text, embedding, updated_at
    ) VALUES %s
    ON CONFLICT (record_key) DO UPDATE SET
        url = EXCLUDED.url,
        project_name = EXCLUDED.project_name,
        architect = EXCLUDED.architect,
        location_country = EXCLUDED.location_country,
        area = EXCLUDED.area,
        program = EXCLUDED.program,
        year = EXCLUDED.year,
        mood = EXCLUDED.mood,
        material = EXCLUDED.material,
        document_text = EXCLUDED.document_text,
        embedding = EXCLUDED.embedding,
        updated_at = NOW();
    """

    values = []
    for row, emb in zip(rows, embeddings):
        values.append(
            (
                row["record_key"],
                row["url"],
                row["project_name"],
                row["architect"],
                row["location_country"],
                row["area"],
                row["program"],
                row["year"],
                row["mood"],
                row["material"],
                row["document_text"],
                to_vector_literal(emb),
            )
        )

    with conn.cursor() as cur:
        template = "(" + ",".join(["%s"] * 11) + ",%s::vector,NOW())"
        execute_values(cur, sql, values, template=template)
    conn.commit()


def show_popup_preview(
    cfg: DbConfig,
    table_name: str,
    json_count: int,
    db_count: int,
    model_dim: int | None,
    db_dim: int | None,
    preview_limit: int = 30,
) -> None:
    import tkinter as tk
    from tkinter import ttk

    conn = psycopg2.connect(
        dbname=cfg.db_name,
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
    )
    try:
        query = f"""
         SELECT id, project_name, architect, location_country, year,
             program, mood, material, LEFT(embedding::text, 60) AS embedding_sample, updated_at
        FROM {table_name}
        ORDER BY id DESC
        LIMIT %s
        """
        with conn.cursor() as cur:
            cur.execute(query, (preview_limit,))
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
    finally:
        conn.close()

    root = tk.Tk()
    root.title("벡터DB 확인 — PostgreSQL")
    root.geometry("1100x600")
    root.resizable(True, True)

    # 상단 요약 정보
    match_symbol = "✅ 일치" if json_count == db_count else "⚠ 불일치"
    summary = (
        f"DB: {cfg.db_name}  |  TABLE: {table_name}  |  "
        f"JSON 건수: {json_count}  |  DB 건수: {db_count}  |  {match_symbol}  |  "
        f"모델 차원: {model_dim}  |  DB 컬럼 차원: {db_dim}"
    )
    tk.Label(root, text=summary, font=("맑은 고딕", 10), anchor="w", fg="#1a1a2e",
             bg="#e8f4f8", relief="flat", padx=8, pady=6).pack(fill="x")

    tk.Label(root, text=f"최근 {preview_limit}건 (id DESC)",
             font=("맑은 고딕", 9), anchor="w", fg="gray", padx=8).pack(fill="x")

    # 테이블
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=8, pady=4)

    vsb = ttk.Scrollbar(frame, orient="vertical")
    hsb = ttk.Scrollbar(frame, orient="horizontal")
    tree = ttk.Treeview(frame, columns=columns, show="headings",
                        yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    vsb.config(command=tree.yview)
    hsb.config(command=tree.xview)
    vsb.pack(side="right", fill="y")
    hsb.pack(side="bottom", fill="x")
    tree.pack(fill="both", expand=True)

    col_widths = {"id": 50, "project_name": 280, "architect": 180, "location_country": 110,
                  "year": 70, "program": 90, "mood": 90, "material": 100, "embedding_sample": 200,
                  "updated_at": 160}
    for col in columns:
        tree.heading(col, text=col)
        tree.column(col, width=col_widths.get(col, 120), anchor="w")

    style = ttk.Style()
    style.configure("Treeview", rowheight=22, font=("맑은 고딕", 9))
    style.configure("Treeview.Heading", font=("맑은 고딕", 9, "bold"))

    for i, row in enumerate(rows):
        tag = "even" if i % 2 == 0 else "odd"
        tree.insert("", "end", values=row, tags=(tag,))
    tree.tag_configure("even", background="#f7f9fc")
    tree.tag_configure("odd", background="#ffffff")

    tk.Button(root, text="닫기", command=root.destroy,
              font=("맑은 고딕", 10), padx=20, pady=4).pack(pady=6)

    root.mainloop()


def export_preview(conn: Any, view_name: str, out_path: Path, limit: int) -> None:
    query = f"""
    SELECT
        id,
        url,
        project_name,
        architect,
        location_country,
        area,
        program,
        year,
        mood,
        material,
        LEFT(document_text, 180) AS document_preview,
        LEFT(embedding::text, 180) AS embedding_preview,
        updated_at
    FROM {view_name}
    ORDER BY id DESC
    LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (limit,))
        columns = [desc[0] for desc in cur.description]
        data = cur.fetchall()

    preview_df = pd.DataFrame(data, columns=columns)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    preview_df.to_csv(out_path, index=False, encoding="utf-8-sig")


def main() -> None:
    args = parse_args()

    records = read_json(args.json_path)
    rows = normalize_rows(records)
    suppress_model_load_warnings()

    cfg = get_db_config(args)
    conn = psycopg2.connect(
        dbname=cfg.db_name,
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
    )

    try:
        create_schema(conn, args.table, args.view_name)

        documents = [row["document_text"] for row in rows]
        input_count = len(rows)
        model = SentenceTransformer(args.embedding_model)
        model_dim = model.get_sentence_embedding_dimension()
        db_dim = get_table_embedding_dimension(conn, args.table)

        print(f"임베딩 모델: {args.embedding_model}")
        print(f"모델 임베딩 차원: {model_dim}")
        if db_dim is not None:
            print(f"DB embedding 컬럼 차원: {db_dim}")
        else:
            print("DB embedding 컬럼 차원: 확인 불가")
        print(f"JSON 데이터 건수: {input_count}")

        batch_size = max(1, args.batch_size)
        printed_generated_dim = False
        for start in range(0, len(rows), batch_size):
            end = start + batch_size
            batch_rows = rows[start:end]
            batch_docs = documents[start:end]
            batch_embeddings = model.encode(batch_docs, normalize_embeddings=True).tolist()
            if not printed_generated_dim and batch_embeddings:
                print(f"생성된 임베딩 차원(샘플): {len(batch_embeddings[0])}")
                printed_generated_dim = True
            upsert_rows(conn, args.table, batch_rows, batch_embeddings)
            print(f"업서트 완료: {start + 1}~{min(end, len(rows))}")

        db_count = get_table_row_count(conn, args.table)
        print(f"벡터DB 테이블 건수: {db_count}")
        if db_count == input_count:
            print("건수 검증: JSON과 벡터DB 건수가 동일합니다.")
        else:
            print("건수 검증: JSON과 벡터DB 건수가 다릅니다.")

        export_preview(conn, args.view_name, args.preview_path, args.preview_size)
        print(f"미리보기 파일 생성: {args.preview_path}")
        export_vector_db_file(conn, args.table, args.vector_db_file_path)
        print(f"벡터DB 파일 생성: {args.vector_db_file_path}")
        print(
            f"완료: PostgreSQL DB={cfg.db_name}, TABLE={args.table}, VIEW={args.view_name}"
        )
    finally:
        conn.close()

    show_popup_preview(
        cfg=cfg,
        table_name=args.table,
        json_count=input_count,
        db_count=db_count,
        model_dim=model_dim,
        db_dim=db_dim,
    )


if __name__ == "__main__":
    main()
