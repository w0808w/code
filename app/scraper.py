from __future__ import annotations

import json
from typing import Any, Dict, List

from bs4 import BeautifulSoup


def _get_text(el) -> str:
    return (el.get_text(strip=True) if el else "").strip()


def parse_workbook_html(html: str) -> List[Dict[str, Any]]:
    """Parse BOJ workbook page table rows into structured rows.

    Expected columns: [문제ID, 제목, 정보, 맞힌 사람, 제출, 정답 비율]
    This parser is defensive against slight structure variations.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    tbody = table.find("tbody") or table
    rows: List[Dict[str, Any]] = []
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        # 문제 ID
        problem_id_text = _get_text(tds[0])
        try:
            problem_id = int(problem_id_text)
        except Exception:
            continue

        # 제목
        title_link = tds[1].find("a")
        title = _get_text(title_link or tds[1])

        # 정보(라벨 등)
        info = _get_text(tds[2]) if len(tds) > 2 else None

        # 맞힌 사람, 제출, 정답 비율 (열 위치는 예제 HTML 기준 3,4,5)
        solved_count = None
        submission_count = None
        ratio = None
        if len(tds) >= 6:
            solved_count_text = _get_text(tds[3])
            submission_count_text = _get_text(tds[4])
            ratio = _get_text(tds[5])
            try:
                solved_count = int(solved_count_text)
            except Exception:
                solved_count = None
            try:
                submission_count = int(submission_count_text)
            except Exception:
                submission_count = None

        rows.append(
            {
                "problem_id": problem_id,
                "title": title,
                "info": info or None,
                "solved_count": solved_count,
                "submission_count": submission_count,
                "ratio": ratio,
            }
        )
    return rows


def parse_problem_detail_html(html: str) -> Dict[str, Any]:
    """Parse a single BOJ problem page for metadata and sections."""
    soup = BeautifulSoup(html, "lxml")

    # problem id from meta or URL menu
    meta = soup.find("meta", attrs={"name": "problem-id"})
    problem_id = None
    if meta and meta.get("content"):
        try:
            problem_id = int(meta.get("content"))
        except Exception:
            problem_id = None

    title_el = soup.find(id="problem_title")
    title = _get_text(title_el)

    # metrics table
    time_limit = memory_limit = ratio = None
    submissions = accepted = solved_people = None
    info_table = soup.find("table", id="problem-info")
    if info_table:
        tbody = info_table.find("tbody") or info_table
        tr = tbody.find("tr") if tbody else None
        if tr:
            tds = tr.find_all("td")
            if len(tds) >= 6:
                time_limit = _get_text(tds[0])
                memory_limit = _get_text(tds[1])
                try:
                    submissions = int(_get_text(tds[2]))
                except Exception:
                    submissions = None
                try:
                    accepted = int(_get_text(tds[3]))
                except Exception:
                    accepted = None
                try:
                    solved_people = int(_get_text(tds[4]))
                except Exception:
                    solved_people = None
                ratio = _get_text(tds[5])

    def _outer_html_by_id(element_id: str) -> str:
        el = soup.find(id=element_id)
        return str(el) if el else ""

    description_html = _outer_html_by_id("problem_description")
    input_html = _outer_html_by_id("problem_input")
    output_html = _outer_html_by_id("problem_output")

    # samples: pair inputs/outputs by numeric suffix
    samples: List[Dict[str, str]] = []
    i = 1
    while True:
        si = soup.find(id=f"sample-input-{i}")
        so = soup.find(id=f"sample-output-{i}")
        if not si and not so:
            # also check alternative ids without dashes: sampleinput1
            si = soup.find(id=f"sampleinput{i}")
            so = soup.find(id=f"sampleoutput{i}")
        if not si and not so:
            break
        samples.append(
            {
                "input": si.get_text("\n").strip() if si else "",
                "output": so.get_text("\n").strip() if so else "",
            }
        )
        i += 1

    source_html = ""
    source_section = soup.find("section", id="source")
    if source_section:
        source_html = str(source_section)

    return {
        "problem_id": problem_id,
        "title": title,
        "time_limit": time_limit,
        "memory_limit": memory_limit,
        "submissions": submissions,
        "accepted": accepted,
        "solved_people": solved_people,
        "ratio": ratio,
        "description_html": description_html,
        "input_html": input_html,
        "output_html": output_html,
        "samples_json": json.dumps(samples, ensure_ascii=False),
        "source_html": source_html,
    }


