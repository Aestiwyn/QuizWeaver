"""Explicit Web quiz sources, isolation, metadata, and cognitive UI visibility."""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.agents import Orchestrator
from src.database import LessonLog, Question, Quiz, get_session
from src.quiz_generator import generate_quiz


def add_lesson(app, class_id, *, days_ago=0, content="Manual lesson", topics=None, filename=None, extracted=None):
    with get_session(app.config["DB_ENGINE"]) as session:
        lesson = LessonLog(
            class_id=class_id,
            date=date.today() - timedelta(days=days_ago),
            content=content,
            topics=json.dumps(topics or []),
            notes="Teacher-only note",
            original_filename=filename,
            stored_filename=None,
            extracted_text=extracted,
        )
        session.add(lesson)
        session.commit()
        return lesson.id


def get_quiz(app, quiz_id):
    with get_session(app.config["DB_ENGINE"]) as session:
        quiz = session.get(Quiz, quiz_id)
        return {
            "metadata": json.loads(quiz.generation_metadata),
            "profile": json.loads(quiz.style_profile),
            "count": session.query(Question).filter_by(quiz_id=quiz_id).count(),
        }


def standard_form(source_mode="current_input", **overrides):
    values = {
        "source_mode": source_mode,
        "num_questions": "5",
        "grade_level": "7th Grade",
        "sol_standards": "SOL 7.1",
        "difficulty": "3",
        "provider": "mock",
        "question_types": ["mc", "tf"],
    }
    values.update(overrides)
    return values


def test_generate_form_lists_only_current_class_lessons_and_preselects_detail_link(flask_client, flask_app):
    chosen = add_lesson(
        flask_app,
        1,
        content="Chosen body preview",
        topics=["cells", "energy"],
        filename="source lesson.pdf",
        extracted="Extracted file summary text",
    )
    other = add_lesson(flask_app, 2, content="Other class secret", topics=["algebra"])
    page = flask_client.get(f"/classes/1/generate?lesson_id={chosen}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert f'value="{chosen}" selected' in html
    assert f'value="{other}"' not in html
    for value in ["Chosen body preview", "cells, energy", "source lesson.pdf", "Extracted file summary text"]:
        assert value in html
    assert "Other class secret" not in html
    assert 'value="recorded_lesson" checked' in html
    assert '<select name="class_id"' not in html


def test_generate_form_defaults_and_unchanged_controls(flask_client):
    html = flask_client.get("/classes/1/generate").get_data(as_text=True)
    assert 'id="num_questions" name="num_questions" value="5"' in html
    assert html.count('name="question_types"') == 9
    assert 'name="question_types" value="mc" checked' in html
    assert 'name="question_types" value="tf" checked' in html
    for value in ["ma", "fill_in_blank", "short_answer", "matching", "ordering", "stimulus", "cloze"]:
        assert f'name="question_types" value="{value}" checked' not in html
    for marker in ['id="provider"', 'id="difficulty"']:
        assert marker in html
    assert 'name="sol_standards"' not in html
    for hidden in ["Bloom", "Webb's DOK", "cognitive_framework_radio", "cognitive-table", "cognitive_form.js"]:
        assert hidden not in html


@pytest.mark.parametrize(
    "data,error",
    [
        (standard_form("recorded_lesson"), "请选择本班已记录的一条课程"),
        (standard_form("current_input", topics="   ", content_text="\n "), "请至少输入一个主题或本次测验的内容／说明"),
        (standard_form("unexpected", topics="cells"), "请选择有效的内容来源"),
    ],
)
def test_source_validation_preserves_form(flask_client, data, error):
    data.update({"grade_level": "9th Grade", "sol_standards": "CUSTOM.1", "difficulty": "4", "provider": "mock"})
    response = flask_client.post("/classes/1/generate", data=data)
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert error in html
    assert 'value="9th Grade"' in html
    assert 'value="4"' in html
    assert 'name="sol_standards"' not in html
    assert 'value="mock"' in html and "selected" in html


def test_recorded_source_ignores_stale_input_and_rejects_other_class(flask_client, flask_app):
    selected = add_lesson(
        flask_app,
        1,
        content="Selected manual",
        topics=["selected topic"],
        filename="selected.pdf",
        extracted="Selected extraction",
    )
    other = add_lesson(flask_app, 2, content="Other class secret", topics=["other secret"])
    mock_quiz = MagicMock(id=88)
    with patch("src.web.blueprints.quizzes.generate_quiz", return_value=mock_quiz) as generate:
        response = flask_client.post(
            "/classes/1/generate",
            data=standard_form(
                "recorded_lesson",
                lesson_id=str(selected),
                topics="STALE TOPIC",
                content_text="STALE CONTENT",
            ),
        )
    assert response.status_code == 303
    args = generate.call_args.kwargs
    assert args["topics"] == "selected topic"
    assert "Selected manual" in args["content_text"] and "Selected extraction" in args["content_text"]
    assert "STALE" not in args["content_text"] and "STALE" not in args["topics"]
    assert args["include_class_history"] is False
    assert args["content_source"] == {
        "type": "recorded_lesson",
        "lesson_id": selected,
        "lesson_date": date.today().isoformat(),
        "topics": ["selected topic"],
        "original_filename": "selected.pdf",
    }
    response = flask_client.post("/classes/1/generate", data=standard_form("recorded_lesson", lesson_id=str(other)))
    assert response.status_code == 404
    assert flask_client.get(f"/classes/1/generate?lesson_id={other}").status_code == 404


def test_current_input_ignores_stale_lesson_id(flask_client, flask_app):
    stale = add_lesson(flask_app, 1, content="STALE LESSON BODY", topics=["stale lesson topic"])
    mock_quiz = MagicMock(id=89)
    with patch("src.web.blueprints.quizzes.generate_quiz", return_value=mock_quiz) as generate:
        response = flask_client.post(
            "/classes/1/generate",
            data=standard_form("current_input", lesson_id=str(stale), topics="fresh topic", content_text="fresh body"),
        )
    assert response.status_code == 303
    args = generate.call_args.kwargs
    assert args["topics"] == "fresh topic" and args["content_text"] == "fresh body"
    assert args["include_class_history"] is False
    assert args["content_source"] == {"type": "current_input", "topics": ["fresh topic"], "has_content": True}


def test_pipeline_history_switch_preserves_generic_compatibility(db_session, mock_config, sample_class):
    session, _db_path = db_session
    class_obj = sample_class(session)
    with patch("src.quiz_generator.run_agentic_pipeline", return_value=([], {})) as pipeline:
        generate_quiz(
            session,
            class_obj.id,
            mock_config,
            topics="cells",
            include_class_history=False,
            content_source={"type": "current_input"},
        )
    context = pipeline.call_args.args[1]
    assert context["lesson_logs"] == [] and context["assumed_knowledge"] == {}
    assert context["content_source"] == {"type": "current_input"}
    assert pipeline.call_args.kwargs["include_class_history"] is False

    with patch("src.quiz_generator.run_agentic_pipeline", return_value=([], {})) as pipeline:
        generate_quiz(session, class_obj.id, mock_config, topics="cells")
    assert pipeline.call_args.kwargs["include_class_history"] is True


def test_agent_pipeline_skips_recent_history_when_disabled(mock_config):
    fake_orchestrator = MagicMock()
    fake_orchestrator.run.return_value = ([], {})
    context = {"content_summary": "Exact source"}
    with (
        patch("src.agents.Orchestrator", return_value=fake_orchestrator),
        patch("src.agents.get_recent_lessons") as recent,
        patch("src.agents.get_assumed_knowledge") as knowledge,
    ):
        from src.agents import run_agentic_pipeline

        run_agentic_pipeline(mock_config, context, class_id=1, web_mode=True, include_class_history=False)
    recent.assert_not_called()
    knowledge.assert_not_called()
    passed = fake_orchestrator.run.call_args.args[0]
    assert passed["lesson_logs"] == [] and passed["assumed_knowledge"] == {}


def test_generator_and_critic_receive_the_same_isolated_source():
    config = {"llm": {"provider": "mock"}, "agent_loop": {"max_retries": 1}}
    generator = MagicMock()
    generator.generate.return_value = [
        {
            "type": "mc",
            "text": "What is the selected source?",
            "options": ["A", "B", "C", "D"],
            "correct_index": 0,
            "points": 1,
        }
    ]
    critic = MagicMock()
    critic.critique.return_value = {
        "status": "APPROVED",
        "feedback": None,
        "passed_indices": [0],
        "failed_indices": [],
        "verdicts": [],
    }
    with (
        patch("src.agents.GeneratorAgent", return_value=generator),
        patch("src.agents.CriticAgent", return_value=critic),
        patch("src.agents.get_qa_guidelines", return_value="rules"),
    ):
        context = {
            "content_summary": "Selected source only",
            "num_questions": 1,
            "lesson_logs": [],
            "assumed_knowledge": {},
            "question_types": ["mc"],
        }
        Orchestrator(config).run(context)
    generator_context = generator.generate.call_args.args[0]
    assert generator_context["content_summary"] == "Selected source only"
    assert generator_context["lesson_logs"] == [] and generator_context["assumed_knowledge"] == {}
    critic_call = critic.critique.call_args
    assert critic_call.args[2] == "Selected source only"
    assert critic_call.kwargs["class_context"] == {"lesson_logs": [], "assumed_knowledge": {}}


def test_web_post_defaults_to_five_questions(flask_client):
    mock_quiz = MagicMock(id=90)
    with patch("src.web.blueprints.quizzes.generate_quiz", return_value=mock_quiz) as generate:
        response = flask_client.post(
            "/classes/1/generate",
            data={"source_mode": "current_input", "topics": "cells"},
        )
    assert response.status_code == 303
    assert generate.call_args.kwargs["num_questions"] == 5


@pytest.mark.parametrize("mode", ["recorded_lesson", "current_input"])
def test_both_sources_generate_in_mock_mode_and_record_metadata(flask_client, flask_app, mode):
    lesson_id = add_lesson(
        flask_app,
        1,
        days_ago=1,
        content="Recorded exact source",
        topics=["mitosis"],
        filename="mitosis.docx",
        extracted="Chromosomes separate during mitosis.",
    )
    # A recent unrelated lesson must not appear in source metadata.
    add_lesson(flask_app, 1, content="RECENT UNRELATED SECRET", topics=["unrelated secret"])
    data = standard_form(mode)
    if mode == "recorded_lesson":
        data["lesson_id"] = str(lesson_id)
    else:
        data.update({"topics": "energy", "content_text": "Energy is conserved."})
    response = flask_client.post("/classes/1/generate", data=data)
    assert response.status_code == 303
    quiz_id = int(response.location.rstrip("/").split("/")[-1])
    saved = get_quiz(flask_app, quiz_id)
    source = saved["metadata"]["content_source"]
    assert source["type"] == mode and saved["count"] == 5
    assert "RECENT UNRELATED SECRET" not in json.dumps(saved["metadata"])
    if mode == "recorded_lesson":
        assert source["lesson_id"] == lesson_id
        assert source["topics"] == ["mitosis"] and source["original_filename"] == "mitosis.docx"
    else:
        assert source == {"type": "current_input", "topics": ["energy"], "has_content": True}


def test_quiz_detail_explains_source_but_hides_historical_cognitive_data(flask_client, flask_app):
    lesson_id = add_lesson(flask_app, 1, content="Source body", topics=["cells"], filename="cells.pdf")
    metadata = {
        "content_source": {
            "type": "recorded_lesson",
            "lesson_id": lesson_id,
            "lesson_date": "2026-09-07",
            "topics": ["cells"],
            "original_filename": "cells.pdf",
        },
        "prompt_summary": {"cognitive_framework": "blooms", "difficulty": 4},
    }
    with get_session(flask_app.config["DB_ENGINE"]) as session:
        quiz = Quiz(
            class_id=1,
            title="Historical Cognitive Quiz",
            status="generated",
            style_profile=json.dumps({"cognitive_framework": "dok", "difficulty": 4}),
            generation_metadata=json.dumps(metadata),
        )
        session.add(quiz)
        session.commit()
        question = Question(
            quiz_id=quiz.id,
            question_type="mc",
            text="Visible question",
            points=1,
            data=json.dumps(
                {"cognitive_level": "Remember", "cognitive_framework": "blooms", "cognitive_level_number": 1}
            ),
        )
        session.add(question)
        session.commit()
        quiz_id = quiz.id
    html = flask_client.get(f"/quizzes/{quiz_id}").get_data(as_text=True)
    for value in ["已记录课程", "2026-09-07", "cells.pdf", "cells", f"/classes/1/lessons/{lesson_id}"]:
        assert value in html
    for hidden in ["Bloom", "blooms", "DOK", "dok", "Cognitive Framework", "cognitive-badge", "Remember"]:
        assert hidden not in html
    with get_session(flask_app.config["DB_ENGINE"]) as session:
        saved = session.get(Quiz, quiz_id)
        assert json.loads(saved.style_profile)["cognitive_framework"] == "dok"
        assert json.loads(saved.generation_metadata)["prompt_summary"]["cognitive_framework"] == "blooms"
        assert json.loads(saved.questions[0].data)["cognitive_level"] == "Remember"
