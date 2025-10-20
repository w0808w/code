from __future__ import annotations

from flask import Blueprint, request, jsonify
from flask import Response

from .gpt_service import GPTService
from .scraper import parse_workbook_html, parse_problem_detail_html
from .db import ensure_tables, upsert_workbook_rows, select_workbook, upsert_problem_detail, get_problem_detail
from .fetcher import http_get, get_workbook_url, get_problem_url


api_bp = Blueprint("api", __name__)
_DB_INIT_DONE = False


@api_bp.before_app_request
def _init_db():
    global _DB_INIT_DONE
    if _DB_INIT_DONE:
        return
    # Initialize DB tables on first request cycle (guarded)
    try:
        ensure_tables()
    except Exception:
        # Fail-soft: keep app booting even if DB not configured yet
        pass
    _DB_INIT_DONE = True


@api_bp.route("/collect/company", methods=["POST"])
def collect_company():
    data = request.get_json(silent=True) or {}
    company = (data.get("company") or "").strip()
    html = data.get("html") or ""
    if company not in {"삼성", "카카오", "LG", "현대"}:
        return jsonify({"error": "invalid_company", "detail": "company must be one of: 삼성, 카카오, LG, 현대"}), 400
    if not html:
        return jsonify({"error": "html_required"}), 400

    rows = parse_workbook_html(html)
    try:
        inserted = upsert_workbook_rows(company, rows)
    except Exception as e:
        return jsonify({"error": "db_error", "detail": str(e)}), 500
    return jsonify({"company": company, "count": len(rows), "upserted": inserted})


@api_bp.route("/problems", methods=["GET"])
def list_problems():
    company = (request.args.get("company") or "").strip()
    if company not in {"삼성", "카카오", "LG", "현대"}:
        return jsonify({"error": "invalid_company", "detail": "company must be one of: 삼성, 카카오, LG, 현대"}), 400
    try:
        rows = select_workbook(company)
    except Exception as e:
        return jsonify({"error": "db_error", "detail": str(e)}), 500
    return jsonify({"company": company, "problems": rows})


@api_bp.route("/collect/problem_details", methods=["POST"])
def collect_problem_details():
    data = request.get_json(silent=True) or {}
    html = data.get("html") or ""
    if not html:
        return jsonify({"error": "html_required"}), 400
    detail = parse_problem_detail_html(html)
    if not detail.get("problem_id"):
        return jsonify({"error": "parse_failed", "detail": "problem_id not found"}), 400
    try:
        upsert_problem_detail(detail)
    except Exception as e:
        return jsonify({"error": "db_error", "detail": str(e)}), 500
    return jsonify({"problem_id": detail["problem_id"], "title": detail.get("title")})


@api_bp.route("/problem/details", methods=["GET"])
def get_details():
    try:
        problem_id = int(request.args.get("problem_id", "0"))
    except Exception:
        return jsonify({"error": "invalid_problem_id"}), 400
    try:
        row = get_problem_detail(problem_id)
    except Exception as e:
        return jsonify({"error": "db_error", "detail": str(e)}), 500
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify(row)


# HTML 없이 URL을 직접 가져와 수집하는 버전들

@api_bp.route("/collect/company_fetch", methods=["POST"])
def collect_company_fetch():
    data = request.get_json(silent=True) or {}
    company = (data.get("company") or "").strip()
    if company not in {"삼성", "카카오", "LG", "현대"}:
        return jsonify({"error": "invalid_company", "detail": "company must be one of: 삼성, 카카오, LG, 현대"}), 400
    url = get_workbook_url(company)
    if not url:
        return jsonify({"error": "no_url"}), 400
    try:
        html = http_get(url)
        rows = parse_workbook_html(html)
        inserted = upsert_workbook_rows(company, rows)
        return jsonify({"company": company, "count": len(rows), "upserted": inserted, "source": url})
    except Exception as e:
        return jsonify({"error": "fetch_or_parse_failed", "detail": str(e)}), 502


@api_bp.route("/collect/problem_fetch", methods=["POST"])
def collect_problem_fetch():
    data = request.get_json(silent=True) or {}
    try:
        problem_id = int(data.get("problem_id"))
    except Exception:
        return jsonify({"error": "invalid_problem_id"}), 400
    url = get_problem_url(problem_id)
    try:
        html = http_get(url)
        detail = parse_problem_detail_html(html)
        if not detail.get("problem_id"):
            detail["problem_id"] = problem_id
        upsert_problem_detail(detail)
        return jsonify({"problem_id": problem_id, "title": detail.get("title"), "source": url})
    except Exception as e:
        return jsonify({"error": "fetch_or_parse_failed", "detail": str(e)}), 502


@api_bp.route("/collect/company_fetch_details", methods=["POST"])
def collect_company_fetch_details():
    data = request.get_json(silent=True) or {}
    company = (data.get("company") or "").strip()
    limit = data.get("limit")
    offset = data.get("offset", 0)
    delay_ms = data.get("delay_ms")  # optional throttle between requests
    timeout_sec = data.get("timeout_sec")  # optional per-request timeout
    if company not in {"삼성", "카카오", "LG", "현대"}:
        return jsonify({"error": "invalid_company", "detail": "company must be one of: 삼성, 카카오, LG, 현대"}), 400
    # 1) 목록을 DB에서 읽고, 2) 각 problem_id에 대해 상세를 fetch
    try:
        rows = select_workbook(company)
        if isinstance(offset, int) and offset > 0:
            rows = rows[offset:]
        if isinstance(limit, int) and limit > 0:
            rows = rows[:limit]
        count = 0
        failed = []
        for r in rows:
            pid = int(r["problem_id"])  # type: ignore[index]
            try:
                url = get_problem_url(pid)
                if isinstance(timeout_sec, int) and timeout_sec > 0:
                    html = http_get(url, timeout=timeout_sec)
                else:
                    html = http_get(url)
                detail = parse_problem_detail_html(html)
                if not detail.get("problem_id"):
                    detail["problem_id"] = pid
                upsert_problem_detail(detail)
                count += 1
                if isinstance(delay_ms, int) and delay_ms > 0:
                    import time
                    time.sleep(delay_ms / 1000.0)
            except Exception as e:
                failed.append({"problem_id": pid, "error": str(e)})
        return jsonify({"company": company, "fetched_details": count, "failed": failed})
    except Exception as e:
        return jsonify({"error": "fetch_or_parse_failed", "detail": str(e)}), 502


@api_bp.route("/problem", methods=["POST"])
def get_problem():
    data = request.get_json(silent=True) or {}
    problem_id = data.get("problem_id")
    if not problem_id:
        return jsonify({"error": "problem_id is required"}), 400

    system = (
        "너는 코딩테스트 출제/채점 보조 AI야. 저작권/정책을 준수해야 해.\n"
        "요청된 문제의 원문을 복제하지 말고, 제목/핵심 내용/입력 형식/출력 형식/제약/예제 입출력을 \n"
        "정확하고 충분히 상세하게 요약해서 제공해."
    )
    user = f"백준 {problem_id}번 문제를 원문 복제 없이, 필요한 모든 정보를 포함해 자세히 요약해줘."

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        link = f"https://www.acmicpc.net/problem/{problem_id}"
        return jsonify({"problem": content, "mode": "summary", "link": link})
    except Exception as e:
        return jsonify({"error": "gpt_request_failed", "detail": str(e)}), 502


@api_bp.route("/submit", methods=["POST"])
def submit_code():
    data = request.get_json(silent=True) or {}
    problem_id = data.get("problem_id")
    problem_text = data.get("problem_text")  # optional: 요약/원문
    language = data.get("language", "python")
    code = data.get("code")
    if not problem_id or not code:
        return jsonify({"error": "problem_id and code are required"}), 400

    system = (
        "너는 코딩테스트 자동 채점기야. 출력은 반드시 '정답' 혹은 '오답'으로 시작하고, "
        "오답이면 틀린 이유를 간결히 설명해."
    )
    user = (
        f"다음은 백준 {problem_id}번 문제에 대한 사용자 코드입니다.\n"
        "문제 조건과 입출력 형식에 맞게 정답 여부를 판별해 주세요.\n"
        "맞으면 \"정답\", 틀리면 \"오답\"이라고 하고, 오답이면 어떤 부분이 잘못되었는지 설명해 주세요.\n\n"
        f"[문제]\n{problem_text or '(생략됨)'}\n\n[사용자 코드]\n{code}\n"
    )

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])

        is_correct = content.strip().startswith("정답")
        return jsonify({"result": "정답" if is_correct else "오답", "detail": content})
    except Exception as e:
        return jsonify({"error": "gpt_request_failed", "detail": str(e)}), 502


@api_bp.route("/custom_submit", methods=["POST"])
def custom_submit():
    data = request.get_json(silent=True) or {}
    problem_text = data.get("problem_text")  # 생성형 문제 전체 텍스트/요약
    language = data.get("language", "python")
    code = data.get("code")
    if not problem_text or not code:
        return jsonify({"error": "problem_text and code are required"}), 400

    system = (
        "너는 코딩테스트 자동 채점기야. 출력은 반드시 '정답' 혹은 '오답'으로 시작하고, "
        "오답이면 틀린 이유를 간결히 설명해."
    )
    user = (
        "다음은 생성된 연습문제와 사용자 코드입니다. 문제 조건과 입출력 형식에 맞게 정답 여부를 판별해 주세요.\n"
        "맞으면 \"정답\", 틀리면 \"오답\"이라고 하고, 오답이면 어떤 부분이 잘못되었는지 설명해 주세요.\n\n"
        f"[문제]\n{problem_text}\n\n[사용자 코드]\n{code}\n"
    )

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        is_correct = content.strip().startswith("정답")
        return jsonify({"result": "정답" if is_correct else "오답", "detail": content})
    except Exception as e:
        return jsonify({"error": "gpt_request_failed", "detail": str(e)}), 502


@api_bp.route("/feedback", methods=["POST"])
def feedback():
    data = request.get_json(silent=True) or {}
    problem_id = data.get("problem_id")
    code = data.get("code")
    if not problem_id or not code:
        return jsonify({"error": "problem_id and code are required"}), 400

    system = (
        "너는 코드 리뷰어야. 오답 코드의 문제점을 명확히 지적하고 개선 포인트를 제시해."
    )
    user = (
        f"백준 {problem_id}번 문제 기준으로, 아래 오답 코드의 문제점과 개선점을 설명해줘.\n"
        f"[코드]\n{code}"
    )

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return jsonify({"feedback": content})
    except Exception as e:
        return jsonify({"error": "gpt_request_failed", "detail": str(e)}), 502


@api_bp.route("/custom_feedback", methods=["POST"])
def custom_feedback():
    data = request.get_json(silent=True) or {}
    problem_text = data.get("problem_text")
    code = data.get("code")
    if not problem_text or not code:
        return jsonify({"error": "problem_text and code are required"}), 400

    system = (
        "너는 코드 리뷰어야. 문제의 요구사항을 기준으로 오답 코드의 문제점을 명확히 지적하고, "
        "개선 포인트와 수정 방향을 제시해. 필요하면 간단한 예시 코드도 포함해."
    )
    user = (
        "다음은 생성된 연습문제와 사용자의 오답 코드입니다.\n"
        "문제의 요구사항 관점에서 어떤 점이 틀렸는지, 어떻게 고치면 좋을지 설명해 주세요.\n\n"
        f"[문제]\n{problem_text}\n\n[오답 코드]\n{code}\n"
    )

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return jsonify({"feedback": content})
    except Exception as e:
        return jsonify({"error": "gpt_request_failed", "detail": str(e)}), 502


@api_bp.route("/new_problem", methods=["POST"])
def new_problem():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic")  # 예: 정렬, 그리디, DP
    difficulty = data.get("difficulty", "중")  # 상/중/하
    last_feedback = data.get("feedback")  # /feedback 응답 텍스트
    last_detail = data.get("detail")  # /submit 응답 detail 텍스트
    learning_goal = data.get("learning_goal")  # 선택: 학습자가 지정

    if not topic and not (last_feedback or last_detail):
        return jsonify({
            "error": "topic_or_feedback_required",
            "detail": "topic 또는 feedback/detail 중 하나는 필요합니다."
        }), 400

    system = (
        "너는 코딩테스트 출제자이자 튜터야. 학습자의 오답 원인을 반영해 맞춤형 연습문제를 한국어로 창작해.\n"
        "요구사항:\n"
        "- 저작권/정책 위반 없이 창작 문제만 제공할 것\n"
        "- 제목, 문제 설명, 입력 형식, 출력 형식, 제약, 예제 입력/출력(2세트 이상), 힌트/학습포인트 포함\n"
        "- 정답 코드는 포함하지 말 것\n"
        "- 난이도와 유형을 명시할 것"
    )

    context_parts = []
    if topic:
        context_parts.append(f"유형: {topic}")
    if difficulty:
        context_parts.append(f"난이도: {difficulty}")
    if learning_goal:
        context_parts.append(f"학습 목표: {learning_goal}")
    if last_feedback:
        context_parts.append(f"오답 피드백:\n{last_feedback}")
    if last_detail and not last_feedback:
        context_parts.append(f"판정 상세(detail):\n{last_detail}")

    context = "\n\n".join(context_parts) if context_parts else "(맥락 없음)"
    user = (
        "아래 맥락(오답 원인/학습 목표)을 반영해 비슷한 난이도의 새로운 연습문제를 만들어줘.\n"
        "반드시 위 요구사항을 모두 만족해줘.\n\n"
        f"[맥락]\n{context}"
    )

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return jsonify({
            "problem": content,
            "topic": topic,
            "difficulty": difficulty,
            "tailored": bool(last_feedback or last_detail or learning_goal),
        })
    except Exception as e:
        return jsonify({"error": "gpt_request_failed", "detail": str(e)}), 502


@api_bp.route("/assist", methods=["POST"])
def assist():
    data = request.get_json(silent=True) or {}
    question = data.get("question")
    code = data.get("code")
    full_code = data.get("full_code")
    problem_id = data.get("problem_id")
    problem_text = data.get("problem_text")

    if not question:
        return jsonify({"error": "question is required"}), 400

    system = (
        "너는 코딩 도우미야. 사용자의 질문과 코드/문제 맥락을 바탕으로 정확하고 실용적인 도움을 제공해.\n"
        "요구사항:\n"
        "- 핵심 원인 설명 → 수정 방향 → 간단 예시 코드 순으로 제시\n"
        "- 과도한 장황함은 피하고, 필요한 경우만 코드 제시\n"
        "- 보안/정책을 준수하고, 실행 결과를 단정하지 말고 추론 근거를 제시\n"
        "- code가 제공되면 이를 최우선으로 분석하고, full_code는 보조 맥락으로만 참고"
    )

    ctx_parts = []
    # 'code'를 최우선 맥락으로 배치하고, 'full_code'는 참고로 표기
    if code:
        ctx_parts.append(f"코드(중심 분석 대상):\n{code}")
    if problem_id:
        ctx_parts.append(f"문제번호(백준): {problem_id}")
    if problem_text:
        ctx_parts.append(f"문제요약:\n{problem_text}")
    if full_code:
        ctx_parts.append(f"참고(전체코드):\n{full_code}")

    context = "\n\n".join(ctx_parts) if ctx_parts else "(제공된 맥락 없음)"
    user = (
        "다음 질문에 답해줘. 가능하면 핵심/수정방향/예시 순으로 짧고 명확하게.\n\n"
        f"[맥락]\n{context}\n\n[질문]\n{question}"
    )

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return jsonify({"answer": content})
    except Exception as e:
        return jsonify({"error": "gpt_request_failed", "detail": str(e)}), 502


@api_bp.route("/code_only", methods=["POST", "GET"])
def code_only():
    data = request.get_json(silent=True) or {}
    # prompt 우선순위: JSON -> form -> query -> raw body(text)
    prompt = (
        data.get("prompt")
        or request.form.get("prompt")
        or request.args.get("prompt")
    )
    # 선택 맥락: 문제 텍스트(생성형) / 백준 문제번호
    problem_text = (
        data.get("problem_text")
        or request.form.get("problem_text")
        or request.args.get("problem_text")
    )
    problem_id_raw = (
        data.get("problem_id")
        or request.form.get("problem_id")
        or request.args.get("problem_id")
    )
    if not prompt:
        try:
            raw_text = request.get_data(cache=False, as_text=True)  # text/plain 지원
            prompt = raw_text if raw_text and raw_text.strip() else None
        except Exception:
            prompt = None

    # code_only: prompt만 사용

    if not prompt:
        return jsonify({"error": "prompt is required", "detail": "Provide prompt in JSON, form, query, or raw body."}), 400

    # 옵션 없음: prompt만 요구

    # 시스템/유저 프롬프트 구성
    system = (
        "너는 코드 생성기야. 다음 요구사항을 만족하는 코드만 출력해."
        "설명, 주석, 마크다운, 앞뒤 텍스트 없이 코드만 출력해."
    )
    # 선택 맥락 구성(있으면 포함)
    ctx_parts = []
    if problem_id_raw is not None and str(problem_id_raw).strip() != "":
        ctx_parts.append(f"문제번호(백준): {str(problem_id_raw).strip()}")
    if problem_text and str(problem_text).strip() != "":
        ctx_parts.append(f"문제설명:\n{str(problem_text).strip()}")

    if ctx_parts:
        user = (
            "아래 맥락을 참고해 요구사항을 만족하는 코드를 출력해. 오직 코드만 출력해야 한다.\n\n"
            f"[맥락]\n{'\n\n'.join(ctx_parts)}\n\n[요구사항]\n{prompt}"
        )
    else:
        user = (
            "다음 요구사항을 만족하는 코드를 출력해. 오직 코드만 출력해야 한다.\n\n"
            f"[요구사항]\n{prompt}"
        )

    def _strip_code_fences(text: str) -> str:
        s = (text or "").lstrip("\ufeff").strip()
        if s.startswith("```"):
            lines = s.splitlines()
            # 시작 펜스 제거
            i_start = 1
            # 끝 펜스 탐색(마지막 펜스 라인)
            i_end = len(lines)
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith("```"):
                    i_end = i
                    break
            core = "\n".join(lines[i_start:i_end]).strip()
            return core
        # 본문 중간에 펜스가 있는 경우 첫 블록만 추출
        if "```" in s:
            first = s.find("```")
            second = s.find("```", first + 3)
            third = s.find("```", second + 3) if second != -1 else -1
            if second != -1 and third != -1:
                inner = s[second + 3:third]
                return inner.strip()
        return s

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])

        code_only = _strip_code_fences(content)
        return Response(code_only, mimetype="text/plain; charset=utf-8")
    except Exception as e:
        # 가능하면 API 오류 코드를 그대로 전달
        status = getattr(e, "status_code", None)
        if status is None:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
        if isinstance(status, int) and status in {400, 401, 403, 404, 409, 422, 429}:
            return jsonify({"error": "gpt_request_failed", "detail": str(e)}), status
        return jsonify({"error": "gpt_request_failed", "detail": str(e)}), 502


@api_bp.route("/compare_with_gpt", methods=["POST"])
def compare_with_gpt():
    data = request.get_json(silent=True) or {}
    # Accept both "code" and "user_code" for flexibility
    user_code = data.get("code") or data.get("user_code")
    language = data.get("language", "python")
    problem_text = data.get("problem_text")  # optional
    problem_id_raw = data.get("problem_id")
    problem_id = None
    if problem_id_raw is not None and str(problem_id_raw).strip() != "":
        try:
            problem_id = int(problem_id_raw)
        except Exception:
            return jsonify({"error": "invalid_problem_id"}), 400

    if not user_code:
        return jsonify({"error": "code is required", "detail": "Provide user's correct code in 'code' or 'user_code'."}), 400

    def _strip_code_fences(text: str) -> str:
        s = (text or "").lstrip("\ufeff").strip()
        if s.startswith("```"):
            lines = s.splitlines()
            i_start = 1
            i_end = len(lines)
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith("```"):
                    i_end = i
                    break
            core = "\n".join(lines[i_start:i_end]).strip()
            return core
        if "```" in s:
            first = s.find("```")
            second = s.find("```", first + 3)
            third = s.find("```", second + 3) if second != -1 else -1
            if second != -1 and third != -1:
                inner = s[second + 3:third]
                return inner.strip()
        return s

    # 1) GPT가 문제를 풀어 코드 생성
    solve_system = (
        "너는 코딩테스트 문제 해결기야. 다음 요구를 따르며 정답 코드를 생성해.\n"
        "- 출력은 오직 코드만: 설명/주석/마크다운 금지.\n"
        "- 표준입출력을 사용하고, 빠르고 견고하게 작성해.\n"
        f"- 언어: {language}\n"
    )

    if problem_text and str(problem_text).strip():
        solve_user = (
            "다음 문제 설명을 바탕으로 정답 코드를 작성해. 오직 코드만 출력해.\n\n"
            f"[문제]\n{problem_text}\n"
        )
    elif isinstance(problem_id, int):
        solve_user = (
            f"백준 {problem_id}번 문제의 정답 코드를 작성해. 오직 코드만 출력해.\n"
            "입출력은 표준입출력을 사용하고, 타임아웃을 고려해 효율적으로 작성해."
        )
    else:
        return jsonify({"error": "problem_context_required", "detail": "Provide 'problem_text' for generated problems or 'problem_id' for BOJ problems."}), 400

    try:
        gpt = GPTService()
        gpt_solution_raw = gpt.complete([
            {"role": "system", "content": solve_system},
            {"role": "user", "content": solve_user},
        ])
        gpt_code = _strip_code_fences(gpt_solution_raw)
    except Exception as e:
        return jsonify({"error": "gpt_solve_failed", "detail": str(e)}), 502

    # 2) 사용자 코드와 GPT 코드 비교 리뷰 생성
    review_system = (
        "너는 코드 리뷰어야. 두 코드(사용자 정답, GPT 정답)를 비교해 균형 잡힌 피드백을 제공해.\n"
        "형식: \n"
        "- 사용자가 잘한 점\n"
        "- 개선하면 좋은 점(구체적 제안 포함)\n"
        "- GPT 코드와의 차이점(알고리즘/복잡도/메모리/가독성/에지케이스)\n"
        "- 리팩터링/최적화 아이디어\n"
        "불필요한 장황함은 피하고, 한국어로 명확하게."
    )
    review_user_ctx = [f"언어: {language}"]
    if isinstance(problem_id, int):
        review_user_ctx.insert(0, f"문제번호: {problem_id}")
    if problem_text:
        review_user_ctx.append(f"문제요약:\n{problem_text}")
    review_user = (
        "아래 두 코드를 비교 분석해. 사용자 코드는 정답임을 전제로 장단점을 평가하고 개선점을 제시해.\n\n"
        f"[사용자 코드]\n{user_code}\n\n[GPT 코드]\n{gpt_code}\n\n"
        + "\n".join(review_user_ctx)
    )

    try:
        gpt = GPTService()
        comparison = gpt.complete([
            {"role": "system", "content": review_system},
            {"role": "user", "content": review_user},
        ])
    except Exception as e:
        return jsonify({"error": "gpt_compare_failed", "detail": str(e)}), 502

    return jsonify({
        "problem_id": problem_id,
        "language": language,
        "gpt_code": gpt_code,
        "comparison": comparison,
    })


@api_bp.route("/solve", methods=["POST"])
def solve():
    data = request.get_json(silent=True) or {}
    problem_text = data.get("problem_text")
    problem_id_raw = data.get("problem_id")
    language = data.get("language", "python")

    # 입력 유효성: 둘 중 하나는 필수, 둘 다 동시에 허용(둘 다 있으면 problem_text 우선)
    has_text = isinstance(problem_text, str) and problem_text.strip() != ""
    has_id = problem_id_raw is not None and str(problem_id_raw).strip() != ""
    if not (has_text or has_id):
        return jsonify({"error": "problem_context_required", "detail": "Provide 'problem_text' for generated problems or 'problem_id' for BOJ problems."}), 400

    # 시스템/유저 프롬프트 구성 (코드만 출력)
    solve_system = (
        "너는 코딩테스트 문제 해결기야. 다음 요구를 따르며 정답 코드를 생성해.\n"
        "- 출력은 오직 코드만: 설명/주석/마크다운 금지.\n"
        "- 표준입출력을 사용하고, 빠르고 견고하게 작성해.\n"
        f"- 언어: {language}\n"
    )

    if has_text:
        solve_user = (
            "다음 문제 설명을 바탕으로 정답 코드를 작성해. 오직 코드만 출력해.\n\n"
            f"[문제]\n{problem_text}\n"
        )
    else:
        try:
            problem_id = int(problem_id_raw)
        except Exception:
            return jsonify({"error": "invalid_problem_id"}), 400
        solve_user = (
            f"백준 {problem_id}번 문제의 정답 코드를 작성해. 오직 코드만 출력해.\n"
            "입출력은 표준입출력을 사용하고, 타임아웃을 고려해 효율적으로 작성해."
        )

    def _strip_code_fences(text: str) -> str:
        s = (text or "").lstrip("\ufeff").strip()
        if s.startswith("```"):
            lines = s.splitlines()
            i_start = 1
            i_end = len(lines)
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith("```"):
                    i_end = i
                    break
            core = "\n".join(lines[i_start:i_end]).strip()
            return core
        if "```" in s:
            first = s.find("```")
            second = s.find("```", first + 3)
            third = s.find("```", second + 3) if second != -1 else -1
            if second != -1 and third != -1:
                inner = s[second + 3:third]
                return inner.strip()
        return s

    try:
        gpt = GPTService()
        content = gpt.complete([
            {"role": "system", "content": solve_system},
            {"role": "user", "content": solve_user},
        ])
        code_only = _strip_code_fences(content)
        return Response(code_only, mimetype="text/plain; charset=utf-8")
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status is None:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
        if isinstance(status, int) and status in {400, 401, 403, 404, 409, 422, 429}:
            return jsonify({"error": "gpt_solve_failed", "detail": str(e)}), status
        return jsonify({"error": "gpt_solve_failed", "detail": str(e)}), 502