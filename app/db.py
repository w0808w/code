from __future__ import annotations

import os
import pymysql
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse, unquote


def _get_mysql_conn() -> pymysql.connections.Connection:
    url = os.getenv("MYSQL_URL")
    if url:
        parsed = urlparse(url)
        # Support schemes like mysql or mysql+pymysql; both are fine here
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 3306
        user = unquote(parsed.username or "root")
        password = unquote(parsed.password or "")
        db = (parsed.path or "/boj").lstrip("/") or "boj"
    else:
        host = os.getenv("MYSQL_HOST", "127.0.0.1")
        port_str = os.getenv("MYSQL_PORT", "3306")
        user = os.getenv("MYSQL_USER", "root")
        password = os.getenv("MYSQL_PASSWORD", "")
        db = os.getenv("MYSQL_DB", "boj")
        try:
            port = int(port_str)
        except ValueError:
            port = 3306

    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def ensure_tables() -> None:
    conn = _get_mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS company_workbook_problem (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  company VARCHAR(16) NOT NULL,
                  problem_id INT NOT NULL,
                  title VARCHAR(255) NOT NULL,
                  info VARCHAR(255) NULL,
                  solved_count INT NULL,
                  submission_count INT NULL,
                  ratio VARCHAR(32) NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  UNIQUE KEY uq_company_problem (company, problem_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS problem_detail (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  problem_id INT NOT NULL UNIQUE,
                  title VARCHAR(255) NOT NULL,
                  time_limit VARCHAR(64) NULL,
                  memory_limit VARCHAR(64) NULL,
                  submissions INT NULL,
                  accepted INT NULL,
                  solved_people INT NULL,
                  ratio VARCHAR(32) NULL,
                  description_html MEDIUMTEXT NULL,
                  input_html MEDIUMTEXT NULL,
                  output_html MEDIUMTEXT NULL,
                  samples_json MEDIUMTEXT NULL,
                  source_html MEDIUMTEXT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
    finally:
        conn.close()


def upsert_workbook_rows(company: str, rows: Iterable[Dict[str, Any]]) -> int:
    conn = _get_mysql_conn()
    inserted = 0
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO company_workbook_problem
                      (company, problem_id, title, info, solved_count, submission_count, ratio)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      title = VALUES(title),
                      info = VALUES(info),
                      solved_count = VALUES(solved_count),
                      submission_count = VALUES(submission_count),
                      ratio = VALUES(ratio)
                    """,
                    (
                        company,
                        row.get("problem_id"),
                        row.get("title", ""),
                        row.get("info"),
                        row.get("solved_count"),
                        row.get("submission_count"),
                        row.get("ratio"),
                    ),
                )
                inserted += 1
        return inserted
    finally:
        conn.close()


def select_workbook(company: str) -> List[Dict[str, Any]]:
    conn = _get_mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT company, problem_id, title, info, solved_count, submission_count, ratio FROM company_workbook_problem WHERE company=%s ORDER BY problem_id ASC",
                (company,),
            )
            return list(cur.fetchall())
    finally:
        conn.close()


def upsert_problem_detail(detail: Dict[str, Any]) -> None:
    conn = _get_mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO problem_detail (
                  problem_id, title, time_limit, memory_limit, submissions, accepted, solved_people, ratio,
                  description_html, input_html, output_html, samples_json, source_html
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  title = VALUES(title),
                  time_limit = VALUES(time_limit),
                  memory_limit = VALUES(memory_limit),
                  submissions = VALUES(submissions),
                  accepted = VALUES(accepted),
                  solved_people = VALUES(solved_people),
                  ratio = VALUES(ratio),
                  description_html = VALUES(description_html),
                  input_html = VALUES(input_html),
                  output_html = VALUES(output_html),
                  samples_json = VALUES(samples_json),
                  source_html = VALUES(source_html)
                """,
                (
                    detail.get("problem_id"),
                    detail.get("title", ""),
                    detail.get("time_limit"),
                    detail.get("memory_limit"),
                    detail.get("submissions"),
                    detail.get("accepted"),
                    detail.get("solved_people"),
                    detail.get("ratio"),
                    detail.get("description_html"),
                    detail.get("input_html"),
                    detail.get("output_html"),
                    detail.get("samples_json"),
                    detail.get("source_html"),
                ),
            )
    finally:
        conn.close()


def get_problem_detail(problem_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_mysql_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT problem_id, title, time_limit, memory_limit, submissions, accepted, solved_people, ratio, description_html, input_html, output_html, samples_json, source_html FROM problem_detail WHERE problem_id=%s",
                (problem_id,),
            )
            row = cur.fetchone()
            return row
    finally:
        conn.close()


