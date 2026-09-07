"""Class and lesson management routes."""

import json
import re
from datetime import date
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from src.classroom import (
    LEGACY_CLASS_DISPLAY_NAME,
    LEGACY_CLASS_NAME,
    create_class,
    delete_class,
    get_class,
    list_classes,
    update_class,
)
from src.database import LessonLog, Quiz
from src.lesson_files import lesson_file_path, parse_lesson_file
from src.lesson_tracker import delete_lesson, get_assumed_knowledge, list_lessons, log_lesson
from src.web.blueprints.helpers import _get_session, login_required

classes_bp = Blueprint("classes", __name__)

CLASS_SELECTION_TARGETS = {
    "generate-quiz": {
        "title": "Choose a Class for Quiz Generation",
        "description": "Select the class whose lessons and settings should guide the quiz.",
        "action_label": "Generate Quiz",
    },
    "log-lesson": {
        "title": "Choose a Class for Lesson Logging",
        "description": "Select the class where this lesson record belongs.",
        "action_label": "Log Lesson",
    },
}


@classes_bp.route("/classes")
@login_required
def classes_list():
    """List all classes with lesson and quiz counts."""
    session = _get_session()
    classes = list_classes(session)
    return render_template("classes/list.html", classes=classes)


@classes_bp.route("/classes/select")
@login_required
def class_select():
    """Choose a class for one of the two core Demo workflows."""
    target = request.args.get("target", "")
    selection = CLASS_SELECTION_TARGETS.get(target)
    if selection is None:
        abort(400, description="Invalid class selection target.")

    session = _get_session()
    classes = list_classes(session)
    for cls in classes:
        if target == "generate-quiz":
            cls["action_url"] = url_for("quizzes.quiz_generate", class_id=cls["id"])
        else:
            cls["action_url"] = url_for("classes.lesson_log", class_id=cls["id"])

    return render_template(
        "classes/select.html",
        classes=classes,
        target=target,
        selection=selection,
    )


@classes_bp.route("/classes/new", methods=["GET", "POST"])
@login_required
def class_create():
    """Create a new class via form POST or render creation form on GET."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return render_template(
                "classes/new.html",
                error="Class name is required.",
            ), 400

        session = _get_session()
        grade_level = request.form.get("grade_level", "").strip() or None
        subject = request.form.get("subject", "").strip() or None

        new_cls = create_class(
            session,
            name=name,
            grade_level=grade_level,
            subject=subject,
        )
        flash(f"Class '{new_cls.name}' created successfully.", "success")
        return redirect(url_for("classes.classes_list"), code=303)

    return render_template("classes/new.html")


@classes_bp.route("/classes/<int:class_id>")
@login_required
def class_detail(class_id):
    """Show class detail with knowledge depth, lessons, and quizzes."""
    session = _get_session()
    class_obj = get_class(session, class_id)
    if not class_obj:
        abort(404)

    knowledge = get_assumed_knowledge(session, class_id)
    lessons = list_lessons(session, class_id)
    quizzes = session.query(Quiz).filter_by(class_id=class_id).all()

    return render_template(
        "classes/detail.html",
        class_obj=class_obj,
        knowledge=knowledge,
        lessons=lessons,
        quizzes=quizzes,
    )


@classes_bp.route("/classes/<int:class_id>/edit", methods=["GET", "POST"])
@login_required
def class_edit(class_id):
    """Edit class details via form POST or render edit form on GET."""
    session = _get_session()
    class_obj = get_class(session, class_id)
    if not class_obj:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip() or None
        if class_obj.name == LEGACY_CLASS_NAME and name == LEGACY_CLASS_DISPLAY_NAME:
            name = None
        grade_level = request.form.get("grade_level", "").strip() or None
        subject = request.form.get("subject", "").strip() or None

        update_class(
            session,
            class_id=class_id,
            name=name,
            grade_level=grade_level,
            subject=subject,
        )
        flash("Class updated successfully.", "success")
        return redirect(url_for("classes.class_detail", class_id=class_id), code=303)

    return render_template("classes/edit.html", class_obj=class_obj)


@classes_bp.route("/classes/<int:class_id>/delete", methods=["POST"])
@login_required
def class_delete_route(class_id):
    """Delete a class and redirect to the class list."""
    session = _get_session()
    success = delete_class(session, class_id)
    if not success:
        abort(404)
    flash("Class deleted successfully.", "success")
    return redirect(url_for("classes.classes_list"), code=303)


# --- Lessons ---


@classes_bp.route("/classes/<int:class_id>/lessons")
@login_required
def lessons_list(class_id):
    """List all lessons for a class with parsed topic lists."""
    session = _get_session()
    class_obj = get_class(session, class_id)
    if not class_obj:
        abort(404)

    lessons = list_lessons(session, class_id)

    # Parse topics from JSON strings
    parsed_lessons = []
    for lesson in lessons:
        topics = lesson.topics
        if isinstance(topics, str):
            topics = json.loads(topics)
        parsed_lessons.append(
            {
                "id": lesson.id,
                "date": lesson.date,
                "content": lesson.content,
                "topics": topics or [],
                "notes": lesson.notes,
            }
        )

    return render_template(
        "lessons/list.html",
        class_obj=class_obj,
        lessons=parsed_lessons,
    )


@classes_bp.route("/classes/<int:class_id>/lessons/new", methods=["GET", "POST"])
@login_required
def lesson_log(class_id):
    """Log a new lesson via form POST or render the lesson form on GET."""
    session = _get_session()
    class_obj = get_class(session, class_id)
    if not class_obj:
        abort(404)

    values = {"lesson_date": date.today().isoformat(), "content": "", "topics": "", "notes": ""}
    errors = []
    invalid_date = False
    status = 200
    if request.method == "POST":
        values = {key: request.form.get(key, "") for key in values}
        content = request.form.get("content", "").strip()
        notes = request.form.get("notes", "").strip() or None
        topics_raw = request.form.get("topics", "").strip()
        topics = [t.strip() for t in topics_raw.split(",") if t.strip()] if topics_raw else None

        selected_date = date.today()
        try:
            if values["lesson_date"]:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values["lesson_date"]):
                    raise ValueError
                selected_date = date.fromisoformat(values["lesson_date"])
        except ValueError:
            invalid_date = True
            errors.append("Enter a valid lesson date in YYYY-MM-DD format.")

        upload = request.files.get("lesson_file")
        has_upload = upload is not None and bool(upload.filename)
        extracted_text = None
        if has_upload:
            try:
                file_data, extension, extracted_text = parse_lesson_file(upload)
            except ValueError as exc:
                errors.append(str(exc))
            except Exception:
                current_app.logger.exception("Lesson file parsing failed")
                errors.append("The file could not be parsed. Export a new PDF or DOCX and retry.")
        elif not content:
            errors.append("Enter lesson content or upload a PDF or DOCX with extractable text.")

        status = 400
        if not errors:
            saved_path = None
            try:
                stored_filename = uuid4().hex + extension if has_upload else None
                lesson = log_lesson(
                    session, class_id=class_id, content=content, topics=topics, notes=notes,
                    lesson_date=selected_date, extracted_text=extracted_text,
                    original_filename=upload.filename if has_upload else None,
                    stored_filename=stored_filename, commit=False,
                )
                if has_upload:
                    target = lesson_file_path(current_app.config["LESSON_UPLOAD_DIR"], stored_filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        saved_path = target
                        stream.write(file_data)
                # Resolve the redirect before commit, avoiding a post-commit database read.
                destination = url_for("classes.lesson_detail", class_id=class_id, lesson_id=lesson.id)
                session.commit()
            except Exception:
                session.rollback()
                if saved_path is not None:
                    saved_path.unlink(missing_ok=True)
                current_app.logger.exception("Lesson recording failed")
                errors.append("The lesson could not be saved. Your text is preserved; please retry.")
                status = 500
            else:
                flash("Lesson logged successfully.", "success")
                return redirect(destination, code=303)
        if has_upload:
            errors.append("For security, browsers cannot restore file inputs. Please select the file again before submitting.")

    return render_template(
        "lessons/new.html",
        class_obj=class_obj,
        today=date.today().isoformat(), values=values, errors=errors, invalid_date=invalid_date,
    ), status


@classes_bp.route("/classes/<int:class_id>/lessons/<int:lesson_id>")
@login_required
def lesson_detail(class_id, lesson_id):
    session = _get_session()
    class_obj = get_class(session, class_id)
    lesson = session.query(LessonLog).filter_by(id=lesson_id, class_id=class_id).first()
    if not class_obj or not lesson:
        abort(404)
    topics = json.loads(lesson.topics) if isinstance(lesson.topics, str) else lesson.topics
    return render_template("lessons/detail.html", class_obj=class_obj, lesson=lesson, topics=topics or [])


@classes_bp.route("/classes/<int:class_id>/lessons/<int:lesson_id>/download")
@login_required
def lesson_download(class_id, lesson_id):
    session = _get_session()
    lesson = session.query(LessonLog).filter_by(id=lesson_id, class_id=class_id).first()
    if not get_class(session, class_id) or not lesson or not lesson.stored_filename:
        abort(404)
    try:
        path = lesson_file_path(current_app.config["LESSON_UPLOAD_DIR"], lesson.stored_filename)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    # Preserve the submitted name in the database; strip paths/control characters for the HTTP header.
    download_name = re.sub(r"[\x00-\x1f\x7f]", "", (lesson.original_filename or path.name).replace("\\", "/").split("/")[-1])
    response = send_file(path, as_attachment=True, download_name=download_name or path.name)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@classes_bp.route("/classes/<int:class_id>/lessons/<int:lesson_id>/delete", methods=["POST"])
@login_required
def lesson_delete_route(class_id, lesson_id):
    """Delete a lesson and redirect back to the lesson list."""
    session = _get_session()
    # Verify class exists
    class_obj = get_class(session, class_id)
    if not class_obj:
        abort(404)

    lesson = session.query(LessonLog).filter_by(id=lesson_id, class_id=class_id).first()
    if not lesson:
        abort(404)
    stored_filename = lesson.stored_filename
    success = delete_lesson(session, lesson_id)
    if not success:
        abort(404)
    if stored_filename:
        lesson_file_path(current_app.config["LESSON_UPLOAD_DIR"], stored_filename).unlink(missing_ok=True)
    flash("Lesson deleted successfully.", "success")
    return redirect(url_for("classes.lessons_list", class_id=class_id), code=303)
