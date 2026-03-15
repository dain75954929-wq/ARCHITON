import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg2
from sentence_transformers import SentenceTransformer

DEFAULT_DB_HOST = os.getenv("PGHOST", "localhost")
DEFAULT_DB_PORT = int(os.getenv("PGPORT", "5432"))
DEFAULT_DB_USER = os.getenv("PGUSER", "postgres")
DEFAULT_DB_PASSWORD = os.getenv("PGPASSWORD", "")
DEFAULT_DB_NAME = "into_database"
DEFAULT_TABLE_NAME = "architecture_vectors"
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@dataclass
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    db_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Terminal UI for PostgreSQL vector search"
    )
    parser.add_argument("--db-host", type=str, default=DEFAULT_DB_HOST)
    parser.add_argument("--db-port", type=int, default=DEFAULT_DB_PORT)
    parser.add_argument("--db-user", type=str, default=DEFAULT_DB_USER)
    parser.add_argument("--db-password", type=str, default=DEFAULT_DB_PASSWORD)
    parser.add_argument("--db-name", type=str, default=DEFAULT_DB_NAME)
    parser.add_argument("--table", type=str, default=DEFAULT_TABLE_NAME)
    parser.add_argument("--embedding-model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--top-k", type=int, default=10)
    return parser.parse_args()


def validate_identifier(name: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise SystemExit(f"Invalid SQL identifier: {name}")
    return name


def to_vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"


def print_header(cfg: DbConfig, table: str, model_name: str, model_dim: int | None) -> None:
    print("\n" + "=" * 72)
    print("Vector Search Terminal UI")
    print("- DB      : {}:{} / {}".format(cfg.host, cfg.port, cfg.db_name))
    print("- Table   : {}".format(table))
    print("- Model   : {}".format(model_name))
    print("- Dim     : {}".format(model_dim))
    print("=" * 72)


def print_menu() -> None:
    print("\n[메뉴]")
    print("1) 텍스트 의미 검색")
    print("2) 기준 ID 유사 검색")
    print("3) ID 상세 조회")
    print("4) 테이블 건수/차원 확인")
    print("0) 종료")


def fetch_table_stats(conn: Any, table: str) -> tuple[int, int | None]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        total = int(cur.fetchone()[0])

        cur.execute(
            f"SELECT vector_dims(embedding) FROM {table} WHERE embedding IS NOT NULL LIMIT 1"
        )
        row = cur.fetchone()
        dim = int(row[0]) if row else None

    return total, dim


def search_by_text(conn: Any, table: str, model: SentenceTransformer, query_text: str, top_k: int) -> None:
    vector = model.encode([query_text], normalize_embeddings=True).tolist()[0]
    vector_literal = to_vector_literal(vector)

    sql = f"""
    SELECT
        id,
        source,
        title,
        credit_location,
        credit_year,
        ROUND((1 - (embedding <=> %s::vector))::numeric, 6) AS cosine_similarity
    FROM {table}
    ORDER BY embedding <=> %s::vector
    LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (vector_literal, vector_literal, top_k))
        rows = cur.fetchall()

    print_results(rows, ["id", "source", "title", "location", "year", "score"])


def search_by_id(conn: Any, table: str, base_id: int, top_k: int) -> None:
    sql = f"""
    SELECT
        b.id,
        b.source,
        b.title,
        b.credit_location,
        b.credit_year,
        ROUND((1 - (b.embedding <=> q.embedding))::numeric, 6) AS cosine_similarity
    FROM {table} b
    CROSS JOIN (
        SELECT embedding
        FROM {table}
        WHERE id = %s
    ) q
    WHERE b.id <> %s
    ORDER BY b.embedding <=> q.embedding
    LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (base_id, base_id, top_k))
        rows = cur.fetchall()

    if not rows:
        print("결과가 없습니다. 기준 ID를 확인하세요.")
        return

    print_results(rows, ["id", "source", "title", "location", "year", "score"])


def show_detail_by_id(conn: Any, table: str, row_id: int) -> None:
    sql = f"""
    SELECT
        id,
        source,
        title,
        url,
        credit_location,
        credit_year,
        image_count,
        LEFT(document_text, 220) AS document_preview,
        LEFT(embedding::text, 120) AS embedding_preview,
        updated_at
    FROM {table}
    WHERE id = %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (row_id,))
        row = cur.fetchone()

    if not row:
        print("해당 ID가 없습니다.")
        return

    labels = [
        "id",
        "source",
        "title",
        "url",
        "location",
        "year",
        "image_count",
        "document_preview",
        "embedding_preview",
        "updated_at",
    ]
    print("\n[상세 정보]")
    for key, value in zip(labels, row):
        print(f"- {key}: {value}")


def print_results(rows: list[tuple[Any, ...]], headers: list[str]) -> None:
    print("\n[검색 결과]")
    if not rows:
        print("결과가 없습니다.")
        return

    widths = [6, 12, 52, 26, 6, 10]
    header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-" * len(header_line))

    for row in rows:
        values: list[str] = []
        for i, item in enumerate(row):
            text = str(item)
            max_w = widths[i]
            if len(text) > max_w:
                text = text[: max_w - 1] + "…"
            values.append(text.ljust(max_w))
        print(" | ".join(values))


def main() -> None:
    args = parse_args()
    table = validate_identifier(args.table)

    cfg = DbConfig(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=args.db_password,
        db_name=args.db_name,
    )

    try:
        conn = psycopg2.connect(
            dbname=cfg.db_name,
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
        )
    except Exception as exc:
        raise SystemExit(f"DB 연결 실패: {exc}") from exc

    try:
        print("임베딩 모델 로딩 중...")
        model = SentenceTransformer(args.embedding_model)
        model_dim = model.get_sentence_embedding_dimension()

        print_header(cfg, table, args.embedding_model, model_dim)

        while True:
            print_menu()
            choice = input("선택 > ").strip()

            if choice == "0":
                print("종료합니다.")
                break

            if choice == "1":
                query_text = input("검색어 입력 > ").strip()
                if not query_text:
                    print("검색어를 입력하세요.")
                    continue
                top_k = input(f"Top-K (기본 {args.top_k}) > ").strip()
                k = int(top_k) if top_k.isdigit() else args.top_k
                search_by_text(conn, table, model, query_text, max(1, k))
                continue

            if choice == "2":
                base = input("기준 ID 입력 > ").strip()
                if not base.isdigit():
                    print("숫자 ID를 입력하세요.")
                    continue
                top_k = input(f"Top-K (기본 {args.top_k}) > ").strip()
                k = int(top_k) if top_k.isdigit() else args.top_k
                search_by_id(conn, table, int(base), max(1, k))
                continue

            if choice == "3":
                row_id = input("조회할 ID 입력 > ").strip()
                if not row_id.isdigit():
                    print("숫자 ID를 입력하세요.")
                    continue
                show_detail_by_id(conn, table, int(row_id))
                continue

            if choice == "4":
                total, dim = fetch_table_stats(conn, table)
                print("\n[테이블 상태]")
                print(f"- total_rows: {total}")
                print(f"- embedding_dims: {dim}")
                continue

            print("메뉴 번호를 다시 입력하세요.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중단되었습니다.")
        sys.exit(0)
