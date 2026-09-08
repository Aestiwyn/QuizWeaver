"""Quiz listing, detail, export, editing API, generation, costs, TTS, and image search routes."""

import json
import logging
import os
import re
import uuid
from io import BytesIO

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask import session as flask_session

from src.classroom import get_class, list_classes
from src.cost_tracking import check_budget, estimate_pipeline_cost, get_cost_summary, get_monthly_total
from src.database import LessonLog, Question, Quiz, Rubric
from src.export import export_csv, export_docx, export_gift, export_pdf, export_qti, export_quizizz_csv
from src.llm_provider import ProviderError, get_provider_info
from src.quiz_generator import generate_quiz
from src.time_utils import utc_now_naive
from src.tts_generator import (
    bundle_audio_zip,
    generate_quiz_audio,
    get_quiz_audio_dir,
    has_audio,
    is_tts_available,
)
from src.variant_generator import READING_LEVELS
from src.web.blueprints.helpers import ALLOWED_IMAGE_EXTENSIONS, _get_session, flash_generation_error, login_required
from src.web.config_utils import save_config

logger = logging.getLogger(__name__)

quizzes_bp = Blueprint("quizzes", __name__)


TEACHER_REVIEW_PENDING = "pending_teacher_review"
TEACHER_REVIEW_CONFIRMED = "teacher_confirmed"
TEACHER_REVIEW_RECONFIRM = "changes_require_reconfirmation"


def _teacher_review_summary(quiz):
    """Return a safe display state; legacy quizzes are never assumed confirmed."""
    status = getattr(quiz, "teacher_review_status", None) or TEACHER_REVIEW_PENDING
    labels = {
        TEACHER_REVIEW_PENDING: "待教师核对",
        TEACHER_REVIEW_CONFIRMED: "教师已确认",
        TEACHER_REVIEW_RECONFIRM: "内容已修改，请重新核对",
    }
    if status not in labels:
        status = TEACHER_REVIEW_PENDING
    return {
        "status": status,
        "label": labels[status],
        "is_confirmed": status == TEACHER_REVIEW_CONFIRMED,
        "confirmed_at": getattr(quiz, "teacher_confirmed_at", None),
        "confirmed_by": getattr(quiz, "teacher_confirmed_by", None),
    }


def _invalidate_teacher_confirmation(quiz):
    """Require a fresh teacher confirmation after substantive question changes."""
    if not quiz:
        return
    current = getattr(quiz, "teacher_review_status", None) or TEACHER_REVIEW_PENDING
    if current == TEACHER_REVIEW_CONFIRMED:
        quiz.teacher_review_status = TEACHER_REVIEW_RECONFIRM
        quiz.teacher_confirmed_at = None
        quiz.teacher_confirmed_by = None
    elif current not in {TEACHER_REVIEW_PENDING, TEACHER_REVIEW_RECONFIRM}:
        quiz.teacher_review_status = TEACHER_REVIEW_PENDING


def _ai_review_summary(generation_metadata):
    """Translate persisted pipeline review metadata for the quiz detail page."""
    metrics = generation_metadata.get("metrics", {}) if isinstance(generation_metadata, dict) else {}
    status = metrics.get("ai_review_status") if isinstance(metrics, dict) else None
    reason = metrics.get("ai_review_reason") if isinstance(metrics, dict) else None
    messages = {
        ("passed", "approved"): ("检查通过", "检查代理已完成核对并通过本次生成的题目。"),
        ("not_passed", "critic_rejected"): ("检查未通过", "检查代理未通过本次生成草稿。"),
        ("not_passed", "retry_limit"): ("检查未通过", "在达到重试上限前，检查代理未通过足够数量的题目。"),
        ("failed_or_incomplete", "critic_error"): ("检查失败或未完成", "检查代理未能完成核对。当前草稿仍需教师审核。"),
        ("failed_or_incomplete", "insufficient_questions"): (
            "检查失败或未完成",
            "生成器未生成足够的结构有效题目，无法完成检查。",
        ),
        ("failed_or_incomplete", "generator_error"): ("检查失败或未完成", "生成器在 AI 检查前未能完成请求。"),
    }
    label, message = messages.get(
        (status, reason),
        ("AI 检查状态不可用", "此历史测验未保存详细的 AI 检查状态。"),
    )
    return {"status": status or "not_recorded", "reason": reason, "label": label, "message": message}


def _lesson_topics(lesson):
    """Return a lesson's topics as a display-safe list."""
    topics = lesson.topics
    if isinstance(topics, str):
        try:
            topics = json.loads(topics)
        except (json.JSONDecodeError, ValueError):
            topics = [topic.strip() for topic in topics.split(",") if topic.strip()]
    return [str(topic) for topic in (topics or [])]


def _safe_source_filename(filename):
    """Keep a readable basename in generation metadata without path/control text."""
    if not filename:
        return None
    basename = filename.replace("\\", "/").split("/")[-1]
    return re.sub(r"[\x00-\x1f\x7f]", "", basename)[:255] or None


def _lesson_choice(lesson):
    """Build the bounded view model used by the recorded-lesson picker."""
    return {
        "id": lesson.id,
        "date": str(lesson.date),
        "topics": _lesson_topics(lesson),
        "content_preview": (lesson.content or "")[:1000],
        "original_filename": _safe_source_filename(lesson.original_filename),
        "extracted_preview": (lesson.extracted_text or "")[:1000],
        "content_truncated": len(lesson.content or "") > 1000,
        "extracted_truncated": len(lesson.extracted_text or "") > 1000,
    }


@quizzes_bp.route("/quizzes")
@login_required
def quizzes_list():
    """List all quizzes with class names, question counts, search, and pagination."""
    session = _get_session()
    query = session.query(Quiz)

    # Apply optional filters
    search_q = request.args.get("q", "").strip()
    status_filter = request.args.get("status")
    class_id_filter = request.args.get("class_id", type=int)

    if search_q:
        query = query.filter(Quiz.title.ilike(f"%{search_q}%"))
    if status_filter:
        query = query.filter(Quiz.status == status_filter)
    if class_id_filter:
        query = query.filter(Quiz.class_id == class_id_filter)

    # Pagination
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    quizzes = query.order_by(Quiz.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    quiz_data = []
    for q in quizzes:
        class_obj = get_class(session, q.class_id) if q.class_id else None
        question_count = session.query(Question).filter_by(quiz_id=q.id).count()
        quiz_data.append(
            {
                "id": q.id,
                "title": q.title,
                "status": q.status,
                "class_name": class_obj.name if class_obj else "N/A",
                "question_count": question_count,
                "created_at": q.created_at,
            }
        )

    all_classes = list_classes(session)

    return render_template(
        "quizzes/list.html",
        quizzes=quiz_data,
        all_classes=all_classes,
        search_q=search_q,
        status_filter=status_filter,
        class_id_filter=class_id_filter,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@quizzes_bp.route("/quizzes/<int:quiz_id>")
@login_required
def quiz_detail(quiz_id):
    """Show quiz detail with all questions and parsed answer data."""
    session = _get_session()
    quiz = session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        abort(404)

    questions = session.query(Question).filter_by(quiz_id=quiz_id).order_by(Question.sort_order, Question.id).all()
    class_obj = get_class(session, quiz.class_id) if quiz.class_id else None

    parsed_questions = []
    for q in questions:
        data = q.data
        if isinstance(data, str):
            data = json.loads(data)
        parsed_questions.append(
            {
                "id": q.id,
                "type": q.question_type,
                "title": q.title,
                "text": q.text,
                "points": q.points,
                "data": data,
                "saved_to_bank": bool(getattr(q, "saved_to_bank", 0)),
            }
        )

    # Parse style_profile for template use
    style_profile = quiz.style_profile
    if isinstance(style_profile, str):
        try:
            style_profile = json.loads(style_profile)
        except (json.JSONDecodeError, ValueError):
            style_profile = {}
    if not isinstance(style_profile, dict):
        style_profile = {}

    # Ensure sol_standards is a list, not a JSON string
    sol_val = style_profile.get("sol_standards")
    if isinstance(sol_val, str):
        try:
            parsed = json.loads(sol_val)
            if isinstance(parsed, list):
                style_profile["sol_standards"] = parsed
            else:
                style_profile["sol_standards"] = [sol_val] if sol_val.strip() else []
        except (json.JSONDecodeError, ValueError):
            # Comma-separated string fallback
            style_profile["sol_standards"] = [s.strip() for s in sol_val.split(",") if s.strip()]

    # Parse generation metadata for Glass Box display
    generation_metadata = getattr(quiz, "generation_metadata", None)
    if isinstance(generation_metadata, str):
        try:
            generation_metadata = json.loads(generation_metadata)
        except (json.JSONDecodeError, ValueError):
            generation_metadata = None
    if not isinstance(generation_metadata, dict):
        generation_metadata = None
    ai_review = _ai_review_summary(generation_metadata)
    teacher_review = _teacher_review_summary(quiz)

    # Variant lineage info
    parent_quiz = None
    if quiz.parent_quiz_id:
        parent_quiz = session.query(Quiz).filter_by(id=quiz.parent_quiz_id).first()

    variant_count = session.query(Quiz).filter_by(parent_quiz_id=quiz_id).count()

    # Rubrics for this quiz
    rubrics = session.query(Rubric).filter_by(quiz_id=quiz_id).order_by(Rubric.created_at.desc()).all()

    # Server-side TTS status
    tts_available = is_tts_available()
    quiz_has_audio = has_audio(quiz_id)

    return render_template(
        "quizzes/detail.html",
        quiz=quiz,
        questions=parsed_questions,
        class_obj=class_obj,
        style_profile=style_profile,
        generation_metadata=generation_metadata,
        ai_review=ai_review,
        teacher_review=teacher_review,
        parent_quiz=parent_quiz,
        variant_count=variant_count,
        rubrics=rubrics,
        reading_levels=READING_LEVELS,
        tts_available=tts_available,
        quiz_has_audio=quiz_has_audio,
    )


@quizzes_bp.route("/quizzes/<int:quiz_id>/confirm", methods=["POST"])
@login_required
def quiz_confirm(quiz_id):
    """Record the current teacher's confirmation for a quiz."""
    session = _get_session()
    quiz = session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        abort(404)

    quiz.teacher_review_status = TEACHER_REVIEW_CONFIRMED
    quiz.teacher_confirmed_at = utc_now_naive()
    quiz.teacher_confirmed_by = flask_session.get("display_name") or flask_session.get("username")
    session.commit()
    flash("测验已确认可用。", "success")
    return redirect(url_for("quizzes.quiz_detail", quiz_id=quiz.id), code=303)


@quizzes_bp.route("/classes/<int:class_id>/quizzes")
@login_required
def class_quizzes(class_id):
    """List quizzes filtered to a specific class."""
    session = _get_session()
    class_obj = get_class(session, class_id)
    if not class_obj:
        abort(404)

    quizzes = session.query(Quiz).filter_by(class_id=class_id).order_by(Quiz.created_at.desc()).all()
    quiz_data = []
    for q in quizzes:
        question_count = session.query(Question).filter_by(quiz_id=q.id).count()
        quiz_data.append(
            {
                "id": q.id,
                "title": q.title,
                "status": q.status,
                "class_name": class_obj.name,
                "question_count": question_count,
                "created_at": q.created_at,
            }
        )
    return render_template(
        "quizzes/list.html",
        quizzes=quiz_data,
        class_obj=class_obj,
    )


# --- Quiz Export ---


@quizzes_bp.route("/quizzes/<int:quiz_id>/export/<format_name>")
@login_required
def quiz_export(quiz_id, format_name):
    """Download a quiz in the requested format (csv, docx, gift, pdf, qti).

    Pass ``?student=1`` to get a student-friendly export (no answers
    highlighted, no cognitive levels, no answer key inline).
    """
    if format_name not in ("csv", "docx", "gift", "pdf", "qti", "quizizz"):
        abort(404)

    session = _get_session()
    quiz = session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        abort(404)

    questions = session.query(Question).filter_by(quiz_id=quiz_id).order_by(Question.sort_order, Question.id).all()

    student_mode = request.args.get("student") == "1"

    # Parse style_profile
    style_profile = quiz.style_profile
    if isinstance(style_profile, str):
        try:
            style_profile = json.loads(style_profile)
        except (json.JSONDecodeError, ValueError):
            style_profile = {}
    if not isinstance(style_profile, dict):
        style_profile = {}

    # Ensure sol_standards is a list, not a JSON string
    sol_val = style_profile.get("sol_standards")
    if isinstance(sol_val, str):
        try:
            parsed = json.loads(sol_val)
            if isinstance(parsed, list):
                style_profile["sol_standards"] = parsed
            else:
                style_profile["sol_standards"] = [sol_val] if sol_val.strip() else []
        except (json.JSONDecodeError, ValueError):
            style_profile["sol_standards"] = [s.strip() for s in sol_val.split(",") if s.strip()]

    # Sanitize title for filename
    safe_title = re.sub(r"[^\w\s\-]", "", quiz.title or "quiz")
    safe_title = re.sub(r"\s+", "_", safe_title.strip())[:80] or "quiz"
    suffix = "_student" if student_mode else ""
    image_dir = _get_upload_dir()
    # Include audio references in exports when audio has been generated
    quiz_audio_dir = get_quiz_audio_dir(quiz_id) if has_audio(quiz_id) else None

    if format_name == "csv":
        csv_str = export_csv(quiz, questions, style_profile, student_mode=student_mode)
        buf = BytesIO(csv_str.encode("utf-8"))
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"{safe_title}{suffix}.csv",
            mimetype="text/csv",
        )
    elif format_name == "docx":
        buf = export_docx(
            quiz, questions, style_profile, student_mode=student_mode, image_dir=image_dir, audio_dir=quiz_audio_dir
        )
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"{safe_title}{suffix}.docx",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    elif format_name == "gift":
        gift_str = export_gift(quiz, questions)
        buf = BytesIO(gift_str.encode("utf-8"))
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"{safe_title}.gift.txt",
            mimetype="text/plain",
        )
    elif format_name == "pdf":
        buf = export_pdf(
            quiz, questions, style_profile, student_mode=student_mode, image_dir=image_dir, audio_dir=quiz_audio_dir
        )
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"{safe_title}{suffix}.pdf",
            mimetype="application/pdf",
        )
    elif format_name == "qti":
        buf = export_qti(quiz, questions, image_dir=image_dir, audio_dir=quiz_audio_dir)
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"{safe_title}.qti.zip",
            mimetype="application/zip",
        )
    elif format_name == "quizizz":
        csv_str = export_quizizz_csv(quiz, questions, style_profile)
        buf = BytesIO(csv_str.encode("utf-8"))
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"{safe_title}_quizizz.csv",
            mimetype="text/csv",
        )


# --- Quiz Editing API ---


@quizzes_bp.route("/api/quizzes/<int:quiz_id>/title", methods=["PUT"])
@login_required
def api_quiz_title(quiz_id):
    """Update quiz title."""
    session = _get_session()
    quiz = session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        return jsonify({"ok": False, "error": "未找到测验"}), 404
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "标题不能为空"}), 400
    quiz.title = title
    session.commit()
    return jsonify({"ok": True, "title": quiz.title})


@quizzes_bp.route("/api/questions/<int:question_id>", methods=["PUT"])
@login_required
def api_question_edit(question_id):
    """Update question text, points, type, options, correct answer."""
    session = _get_session()
    question = session.query(Question).filter_by(id=question_id).first()
    if not question:
        return jsonify({"ok": False, "error": "Question not found"}), 404
    payload = request.get_json(silent=True) or {}

    # Update scalar fields
    if "text" in payload:
        text = (payload["text"] or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "题干不能为空"}), 400
        question.text = text
    if "points" in payload:
        question.points = float(payload["points"])
    if "question_type" in payload:
        question.question_type = payload["question_type"]

    # Merge into data JSON
    q_data = question.data
    if isinstance(q_data, str):
        q_data = json.loads(q_data)
    if not isinstance(q_data, dict):
        q_data = {}

    if "text" in payload:
        q_data["text"] = question.text
    if "question_type" in payload:
        q_data["type"] = payload["question_type"]
    if "options" in payload:
        q_data["options"] = payload["options"]
    if "correct_index" in payload:
        q_data["correct_index"] = payload["correct_index"]
    if "correct_answer" in payload:
        q_data["correct_answer"] = payload["correct_answer"]
    if "points" in payload:
        q_data["points"] = question.points

    question.data = q_data
    # Force SQLAlchemy to detect the JSON change
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(question, "data")
    _invalidate_teacher_confirmation(session.query(Quiz).filter_by(id=question.quiz_id).first())
    session.commit()

    return jsonify(
        {
            "ok": True,
            "question": {
                "id": question.id,
                "text": question.text,
                "points": question.points,
                "question_type": question.question_type,
                "data": question.data,
            },
        }
    )


@quizzes_bp.route("/api/questions/<int:question_id>", methods=["DELETE"])
@login_required
def api_question_delete(question_id):
    """Delete a question from its quiz."""
    session = _get_session()
    question = session.query(Question).filter_by(id=question_id).first()
    if not question:
        return jsonify({"ok": False, "error": "未找到题目"}), 404
    _invalidate_teacher_confirmation(session.query(Quiz).filter_by(id=question.quiz_id).first())
    session.delete(question)
    session.commit()
    return jsonify({"ok": True})


@quizzes_bp.route("/api/quizzes/<int:quiz_id>/reorder", methods=["PUT"])
@login_required
def api_quiz_reorder(quiz_id):
    """Reorder questions within a quiz."""
    session = _get_session()
    quiz = session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        return jsonify({"ok": False, "error": "Quiz not found"}), 404
    payload = request.get_json(silent=True) or {}
    question_ids = payload.get("question_ids", [])

    # Validate: the IDs must exactly match the quiz's question IDs
    actual_ids = set(row[0] for row in session.query(Question.id).filter_by(quiz_id=quiz_id).all())
    if set(question_ids) != actual_ids:
        return jsonify({"ok": False, "error": "题目 ID 与测验不匹配"}), 400

    for idx, qid in enumerate(question_ids):
        session.query(Question).filter_by(id=qid).update({"sort_order": idx})
    session.commit()
    return jsonify({"ok": True})


def _get_upload_dir():
    """Return the absolute path to the image uploads directory, creating it if needed."""
    config = current_app.config["APP_CONFIG"]
    upload_dir = os.path.abspath(config.get("paths", {}).get("upload_dir", "uploads/images"))
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _validate_image_file(field_name="image"):
    """Validate an uploaded image file from the request.

    Returns (file, ext) on success or (None, error_response) on failure.
    """
    if field_name not in request.files:
        return None, (jsonify({"ok": False, "error": "未提供图片文件"}), 400)
    file = request.files[field_name]
    if not file.filename:
        return None, (jsonify({"ok": False, "error": "No image file provided"}), 400)

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None, (
            jsonify({"ok": False, "error": f"文件类型无效。允许：{', '.join(ALLOWED_IMAGE_EXTENSIONS)}"}),
            400,
        )
    return file, ext


def _save_uploaded_image(file, ext):
    """Save an uploaded file with a UUID filename. Returns the filename."""
    filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = _get_upload_dir()
    file.save(os.path.join(upload_dir, filename))
    return filename


@quizzes_bp.route("/api/upload-image", methods=["POST"])
@login_required
def api_upload_image():
    """Upload an image file and return its URL.

    Accepts multipart form data with an 'image' field.
    Returns JSON ``{"ok": true, "url": "/uploads/images/<uuid>.<ext>", "filename": "<uuid>.<ext>"}``.
    """
    file, ext_or_error = _validate_image_file()
    if file is None:
        return ext_or_error

    filename = _save_uploaded_image(file, ext_or_error)
    return jsonify({"ok": True, "url": f"/uploads/images/{filename}", "filename": filename})


@quizzes_bp.route("/api/questions/<int:question_id>/image", methods=["POST"])
@login_required
def api_question_image_upload(question_id):
    """Upload an image for a question."""
    session = _get_session()
    question = session.query(Question).filter_by(id=question_id).first()
    if not question:
        return jsonify({"ok": False, "error": "Question not found"}), 404

    file, ext_or_error = _validate_image_file()
    if file is None:
        return ext_or_error

    filename = _save_uploaded_image(file, ext_or_error)

    # Update question data
    q_data = question.data
    if isinstance(q_data, str):
        q_data = json.loads(q_data)
    if not isinstance(q_data, dict):
        q_data = {}
    q_data["image_ref"] = filename
    q_data.pop("image_description", None)

    question.data = q_data
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(question, "data")
    _invalidate_teacher_confirmation(session.query(Quiz).filter_by(id=question.quiz_id).first())
    session.commit()

    return jsonify({"ok": True, "image_ref": filename, "url": f"/uploads/images/{filename}"})


@quizzes_bp.route("/api/questions/<int:question_id>/image", methods=["DELETE"])
@login_required
def api_question_image_remove(question_id):
    """Remove image reference from a question (does not delete file)."""
    session = _get_session()
    question = session.query(Question).filter_by(id=question_id).first()
    if not question:
        return jsonify({"ok": False, "error": "Question not found"}), 404

    q_data = question.data
    if isinstance(q_data, str):
        q_data = json.loads(q_data)
    if not isinstance(q_data, dict):
        q_data = {}
    q_data.pop("image_ref", None)

    question.data = q_data
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(question, "data")
    _invalidate_teacher_confirmation(session.query(Quiz).filter_by(id=question.quiz_id).first())
    session.commit()

    return jsonify({"ok": True})


@quizzes_bp.route("/api/questions/<int:question_id>/image-description", methods=["DELETE"])
@login_required
def api_question_image_description_remove(question_id):
    """Clear the image_description field from a question's data."""
    session = _get_session()
    question = session.query(Question).filter_by(id=question_id).first()
    if not question:
        return jsonify({"ok": False, "error": "Question not found"}), 404

    q_data = question.data
    if isinstance(q_data, str):
        q_data = json.loads(q_data)
    if not isinstance(q_data, dict):
        q_data = {}
    q_data.pop("image_description", None)

    question.data = q_data
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(question, "data")
    _invalidate_teacher_confirmation(session.query(Quiz).filter_by(id=question.quiz_id).first())
    session.commit()

    return jsonify({"ok": True})


@quizzes_bp.route("/api/questions/<int:question_id>/regenerate", methods=["POST"])
@login_required
def api_question_regenerate(question_id):
    """Regenerate a single question using the LLM."""
    session = _get_session()
    question = session.query(Question).filter_by(id=question_id).first()
    if not question:
        return jsonify({"ok": False, "error": "Question not found"}), 404

    payload = request.get_json(silent=True) or {}
    teacher_notes = (payload.get("teacher_notes") or "").strip()
    quiz_id = question.quiz_id

    config = current_app.config["APP_CONFIG"]
    from src.question_regenerator import regenerate_question

    result = regenerate_question(session, question_id, teacher_notes, config)
    if result is None:
        return jsonify({"ok": False, "error": "重新生成失败"}), 500

    _invalidate_teacher_confirmation(session.query(Quiz).filter_by(id=quiz_id).first())
    session.commit()

    return jsonify(
        {
            "ok": True,
            "question": {
                "id": result.id,
                "text": result.text,
                "points": result.points,
                "question_type": result.question_type,
                "data": result.data
                if isinstance(result.data, dict)
                else json.loads(result.data)
                if isinstance(result.data, str)
                else {},
            },
        }
    )


# --- Quiz Generation ---


@quizzes_bp.route("/generate")
@login_required
def generate_redirect():
    """Start quiz generation by requiring an explicit class choice."""
    return redirect(url_for("classes.class_select", target="generate-quiz"))


@quizzes_bp.route("/classes/<int:class_id>/generate", methods=["GET", "POST"])
@login_required
def quiz_generate(class_id):
    """Generate a quiz for a class via form POST or render the form on GET."""
    session = _get_session()
    class_obj = get_class(session, class_id)
    if not class_obj:
        abort(404)

    config = current_app.config["APP_CONFIG"]
    lessons = (
        session.query(LessonLog).filter_by(class_id=class_id).order_by(LessonLog.date.desc(), LessonLog.id.desc()).all()
    )

    lesson_choices = [_lesson_choice(lesson) for lesson in lessons]
    lesson_by_id = {lesson.id: lesson for lesson in lessons}
    class_standards = getattr(class_obj, "standards", None)
    if isinstance(class_standards, str):
        try:
            class_standards = json.loads(class_standards)
        except (json.JSONDecodeError, ValueError):
            class_standards = [value.strip() for value in class_standards.split(",") if value.strip()]
    if not isinstance(class_standards, list):
        class_standards = []

    requested_lesson_id = (
        request.form.get("lesson_id", "") if request.method == "POST" else request.args.get("lesson_id", "")
    )
    source_mode = (
        request.form.get("source_mode", "current_input")
        if request.method == "POST"
        else ("recorded_lesson" if requested_lesson_id else "current_input")
    )
    source_lesson = None
    if requested_lesson_id and (request.method == "GET" or source_mode == "recorded_lesson"):
        try:
            requested_lesson_id = int(requested_lesson_id)
        except (TypeError, ValueError):
            abort(404)
        source_lesson = lesson_by_id.get(requested_lesson_id)
        # A supplied ID that is absent from this class is treated as tampering.
        if source_lesson is None and (request.method == "GET" or source_mode == "recorded_lesson"):
            abort(404)

    form_values = {
        "source_mode": source_mode,
        "lesson_id": str(requested_lesson_id or ""),
        "topics": request.form.get("topics", "") if request.method == "POST" else "",
        "content_text": request.form.get("content_text", "") if request.method == "POST" else "",
        "num_questions": request.form.get("num_questions", "5") if request.method == "POST" else "5",
        "grade_level": request.form.get("grade_level", getattr(class_obj, "grade_level", "") or "")
        if request.method == "POST"
        else (getattr(class_obj, "grade_level", "") or ""),
        "question_types": request.form.getlist("question_types") if request.method == "POST" else ["mc", "tf"],
        "difficulty": request.form.get("difficulty", "3") if request.method == "POST" else "3",
        "provider": request.form.get("provider", "")
        if request.method == "POST"
        else config.get("last_provider", {}).get("quiz", ""),
    }
    if not form_values["question_types"]:
        form_values["question_types"] = ["mc", "tf"]

    def render_form(error=None, status=200):
        providers = get_provider_info(config)
        return (
            render_template(
                "quizzes/generate.html",
                class_obj=class_obj,
                providers=providers,
                current_provider=config.get("llm", {}).get("provider", "mock"),
                last_provider=form_values["provider"],
                error=error,
                source_lesson=source_lesson,
                lesson_choices=lesson_choices,
                form_values=form_values,
            ),
            status,
        )

    if request.method == "POST":
        if source_mode not in {"recorded_lesson", "current_input"}:
            return render_form("请选择有效的内容来源。", 400)

        if source_mode == "recorded_lesson":
            if not requested_lesson_id:
                return render_form("请选择本班已记录的一条课程。", 400)
            topics_list = _lesson_topics(source_lesson)
            topics = ", ".join(topics_list)
            content_text = source_lesson.generation_content
            content_source = {
                "type": "recorded_lesson",
                "lesson_id": source_lesson.id,
                "lesson_date": str(source_lesson.date),
                "topics": topics_list,
                "original_filename": _safe_source_filename(source_lesson.original_filename),
            }
        else:
            # Ignore a stale lesson_id and use only the fields in this source mode.
            source_lesson = None
            topics = request.form.get("topics", "").strip()
            content_text = request.form.get("content_text", "").strip()
            if not topics and not content_text:
                return render_form("请至少输入一个主题或本次测验的内容／说明。", 400)
            content_source = {
                "type": "current_input",
                "topics": [value.strip() for value in topics.split(",") if value.strip()],
                "has_content": bool(content_text),
            }

        try:
            num_questions = max(1, min(int(request.form.get("num_questions", 5)), 100))
        except (ValueError, TypeError):
            num_questions = 5
        grade_level = request.form.get("grade_level", "").strip() or None
        if "sol_standards" in request.form:
            sol_raw = request.form.get("sol_standards", "").strip()
            sol_standards = [s.strip() for s in sol_raw.split(",") if s.strip()] or None
        else:
            # The Web form no longer exposes manual selection. Keep class-level
            # standards for normal browser submissions while preserving explicit
            # standards from other callers.
            sol_standards = class_standards or None

        # Parse independent question types (F6)
        question_types = request.form.getlist("question_types")
        if not question_types:
            question_types = ["mc", "tf"]  # sensible default

        try:
            difficulty = max(1, min(int(request.form.get("difficulty", 3)), 5))
        except (ValueError, TypeError):
            difficulty = 3

        # Per-quiz provider override
        provider_override = request.form.get("provider", "").strip() or None

        generation_error = None
        try:
            quiz = generate_quiz(
                session,
                class_id=class_id,
                config=config,
                num_questions=num_questions,
                grade_level=grade_level,
                sol_standards=sol_standards,
                cognitive_framework=None,
                cognitive_distribution=None,
                difficulty=difficulty,
                provider_name=provider_override,
                topics=topics,
                content_text=content_text,
                question_types=question_types,
                include_class_history=False,
                content_source=content_source,
            )
        except ProviderError as pe:
            quiz = None
            generation_error = pe.user_message
        except Exception as e:
            quiz = None
            flash_generation_error("Quiz generation", e)
            generation_error = "The generation request could not be completed. Check the server log and try again."

        if quiz:
            # Remember last-used provider for quiz generation
            if provider_override:
                config.setdefault("last_provider", {})["quiz"] = provider_override
                save_config(config)
            flash("测验生成成功。", "success")
            return redirect(url_for("quizzes.quiz_detail", quiz_id=quiz.id), code=303)
        else:
            return render_form(
                generation_error or "The generator did not return a usable quiz. Please revise the input and try again."
            )

    return render_form()


# --- Cost Estimate API ---


@quizzes_bp.route("/api/estimate-cost")
@login_required
def estimate_cost():
    """Return estimated cost for quiz generation based on form parameters."""
    config = current_app.config["APP_CONFIG"]

    # Allow provider override from query param; fall back to config default
    provider_param = request.args.get("provider", "").strip()
    num_questions = request.args.get("num_questions", 10, type=int)
    num_questions = max(1, min(num_questions, 50))

    # Build a temporary config with the requested provider
    estimate_config = dict(config)
    estimate_config["llm"] = dict(config.get("llm", {}))
    if provider_param:
        estimate_config["llm"]["provider"] = provider_param

    try:
        pipeline = estimate_pipeline_cost(estimate_config)
    except Exception:
        return jsonify({"estimated_cost": "$0.00", "error": "无法计算预估费用"})

    is_mock = pipeline["provider"] == "mock"

    if is_mock:
        return jsonify(
            {
                "estimated_cost": "$0.00",
                "estimated_tokens": 0,
                "model": "mock",
                "is_mock": True,
                "message": "Mock mode -- no API costs",
            }
        )

    # Scale estimate by question count (base estimate assumes ~10 questions)
    scale_factor = num_questions / 10.0
    base_cost = pipeline["estimated_max_cost"]
    scaled_cost = base_cost * scale_factor

    # Estimate tokens: ~200 input + ~100 output per question, times pipeline calls
    estimated_tokens = int((200 + 100) * num_questions * pipeline["max_calls"])

    return jsonify(
        {
            "estimated_cost": f"${scaled_cost:.4f}",
            "estimated_cost_raw": round(scaled_cost, 6),
            "estimated_tokens": estimated_tokens,
            "model": pipeline["model"],
            "provider": pipeline["provider"],
            "is_mock": False,
            "max_calls": pipeline["max_calls"],
        }
    )


# --- Costs ---


@quizzes_bp.route("/costs", methods=["GET", "POST"])
@login_required
def costs():
    """Show API cost tracking dashboard with provider info and budget."""
    config = current_app.config["APP_CONFIG"]

    if request.method == "POST":
        budget_raw = request.form.get("monthly_budget", "").strip()
        try:
            budget_val = float(budget_raw) if budget_raw else 0
        except ValueError:
            budget_val = 0
        config.setdefault("llm", {})["monthly_budget"] = budget_val
        save_config(config)
        flash("每月预算已更新。", "success")
        return redirect(url_for("quizzes.costs"), code=303)

    provider = config.get("llm", {}).get("provider", "unknown")
    stats = get_cost_summary()
    budget = check_budget(config)
    monthly = get_monthly_total()
    return render_template(
        "costs.html",
        stats=stats,
        provider=provider,
        budget=budget,
        monthly=monthly,
    )


# --- Image Search API ---


@quizzes_bp.route("/api/image-search")
@login_required
def api_image_search():
    """Search Pixabay for images. Requires PIXABAY_API_KEY in .env."""
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return jsonify(
            {
                "ok": False,
                "configured": False,
                "error": "Pixabay image search is not configured.",
                "setup_url": url_for("settings.pixabay_wizard"),
            }
        )

    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "搜索关键词为必填项。"}), 400

    image_type = request.args.get("type", "illustration").strip()
    if image_type not in ("illustration", "photo", "vector", "all"):
        image_type = "illustration"

    import requests as http_requests

    try:
        resp = http_requests.get(
            "https://pixabay.com/api/",
            params={
                "key": api_key,
                "q": query,
                "image_type": image_type,
                "per_page": 12,
                "safesearch": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("Pixabay API request failed")
        return jsonify({"ok": False, "error": "图片搜索请求失败，请重试。"}), 502

    hits = [
        {
            "id": h.get("id"),
            "thumbnail": h.get("previewURL", ""),
            "medium": h.get("webformatURL", ""),
            "tags": h.get("tags", ""),
            "page_url": h.get("pageURL", ""),
            "width": h.get("webformatWidth", 0),
            "height": h.get("webformatHeight", 0),
        }
        for h in data.get("hits", [])
    ]

    return jsonify({"ok": True, "configured": True, "hits": hits})


@quizzes_bp.route("/api/questions/<int:question_id>/image-from-url", methods=["POST"])
@login_required
def api_question_image_from_url(question_id):
    """Download an image from a URL and attach it to a question."""
    session = _get_session()
    question = session.query(Question).filter_by(id=question_id).first()
    if not question:
        return jsonify({"ok": False, "error": "Question not found"}), 404

    payload = request.get_json(silent=True) or {}
    image_url = (payload.get("url") or "").strip()
    if not image_url:
        return jsonify({"ok": False, "error": "图片 URL 为必填项"}), 400

    import requests as http_requests

    try:
        resp = http_requests.get(image_url, timeout=15, stream=True)
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to download image from URL")
        return jsonify({"ok": False, "error": "无法从提供的 URL 下载图片。"}), 400

    content_type = resp.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        return jsonify({"ok": False, "error": f"URL 未指向图片（内容类型：{content_type}）。"}), 400

    # Check size limit (10 MB)
    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > 10 * 1024 * 1024:
        return jsonify({"ok": False, "error": "图片过大（最大 10 MB）。"}), 400

    # Determine extension from content type
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    ext = ext_map.get(content_type.split(";")[0].strip(), ".jpg")

    filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = _get_upload_dir()
    filepath = os.path.join(upload_dir, filename)

    # Stream to disk with size guard
    total = 0
    max_size = 10 * 1024 * 1024
    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            total += len(chunk)
            if total > max_size:
                f.close()
                os.remove(filepath)
                return jsonify({"ok": False, "error": "Image is too large (max 10 MB)."}), 400
            f.write(chunk)

    # Update question data
    q_data = question.data
    if isinstance(q_data, str):
        q_data = json.loads(q_data)
    if not isinstance(q_data, dict):
        q_data = {}
    q_data["image_ref"] = filename
    q_data.pop("image_description", None)

    question.data = q_data
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(question, "data")
    _invalidate_teacher_confirmation(session.query(Quiz).filter_by(id=question.quiz_id).first())
    session.commit()

    return jsonify({"ok": True, "image_ref": filename, "url": f"/uploads/images/{filename}"})


# --- Server-Side TTS ---


@quizzes_bp.route("/api/quizzes/<int:quiz_id>/tts-status")
@login_required
def api_tts_status(quiz_id):
    """Check TTS availability and whether audio has been generated for a quiz."""
    if not is_tts_available():
        return jsonify({"available": False, "has_audio": False, "message": "请安装 gTTS 以启用音频导出。"})

    return jsonify({"available": True, "has_audio": has_audio(quiz_id)})


@quizzes_bp.route("/quizzes/<int:quiz_id>/generate-audio", methods=["POST"])
@login_required
def quiz_generate_audio(quiz_id):
    """Generate MP3 audio for all questions in a quiz."""
    if not is_tts_available():
        return jsonify({"ok": False, "error": "未安装 gTTS。请运行：pip install gtts"}), 400

    session = _get_session()
    quiz = session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        return jsonify({"ok": False, "error": "Quiz not found"}), 404

    questions = session.query(Question).filter_by(quiz_id=quiz_id).order_by(Question.sort_order, Question.id).all()

    if not questions:
        return jsonify({"ok": False, "error": "测验没有题目"}), 400

    # Build question dicts for the generator
    question_dicts = []
    for q in questions:
        data = q.data
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict):
            data = {}
        question_dicts.append({"id": q.id, "text": q.text or data.get("text", ""), "options": data.get("options", [])})

    lang = request.json.get("lang", "en") if request.is_json else "en"
    audio_dir = get_quiz_audio_dir(quiz_id)

    try:
        results = generate_quiz_audio(question_dicts, audio_dir, lang=lang)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "generated": len(results), "total": len(question_dicts)})


@quizzes_bp.route("/quizzes/<int:quiz_id>/audio/<int:question_id>.mp3")
@login_required
def quiz_serve_audio(quiz_id, question_id):
    """Serve a single question's audio MP3 file."""
    audio_dir = get_quiz_audio_dir(quiz_id)
    filepath = os.path.join(audio_dir, f"q{question_id}.mp3")
    if not os.path.isfile(filepath):
        abort(404)
    return send_file(filepath, mimetype="audio/mpeg")


@quizzes_bp.route("/quizzes/<int:quiz_id>/audio/download")
@login_required
def quiz_download_audio(quiz_id):
    """Download all audio files for a quiz as a ZIP archive."""
    session = _get_session()
    quiz = session.query(Quiz).filter_by(id=quiz_id).first()
    if not quiz:
        abort(404)

    audio_dir = get_quiz_audio_dir(quiz_id)
    if not has_audio(quiz_id):
        abort(404)

    safe_title = re.sub(r"[^\w\s\-]", "", quiz.title or "quiz")
    safe_title = re.sub(r"\s+", "_", safe_title.strip())[:80] or "quiz"

    buf = bundle_audio_zip(audio_dir, quiz_title=safe_title)
    return send_file(buf, as_attachment=True, download_name=f"{safe_title}_audio.zip", mimetype="application/zip")
