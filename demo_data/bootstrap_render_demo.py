"""Create a disposable, deterministic database for the public Render demo.

The bootstrap is deliberately gated behind ``DEMO_MODE`` so normal local and
self-hosted Docker installations keep their existing database untouched.
Render's free filesystem is ephemeral, so recreating the demo database on each
container start gives every new instance the same safe starting state.
"""

import json
import os
import sys
from pathlib import Path

# Make project imports work when this file is executed directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from demo_data.setup_demo import setup_demo_data
from src.classroom import LEGACY_CLASS_NAME
from src.database import Class, Question, Quiz, get_engine, get_session, init_db
from src.web.auth import create_user


def demo_mode_enabled():
    """Return True only for the explicitly configured public demo."""
    return os.environ.get("DEMO_MODE") == "1"


def _seed_quizzes(session):
    """Add a small set of finished quizzes for dashboard and detail views."""
    science = session.query(Class).filter_by(name="七年级科学 A 班").one()
    earth_science = session.query(Class).filter_by(name="八年级地球科学").one()

    quizzes = [
        (
            Quiz(
                title="光合作用知识检查",
                class_id=science.id,
                status="generated",
                style_profile={"grade_level": "七年级", "question_count": 3},
                generation_metadata=json.dumps(
                    {"provider": "mock", "purpose": "公开演示预置内容"}, ensure_ascii=False
                ),
            ),
            [
                (
                    "mc",
                    "植物进行光合作用的主要场所是什么？",
                    {"options": ["叶绿体", "细胞核", "线粒体", "核糖体"], "correct_index": 0},
                ),
                (
                    "tf",
                    "光合作用会释放氧气。",
                    {"is_true": True},
                ),
                (
                    "short_answer",
                    "写出影响光合作用速率的两个因素。",
                    {"answer": "光照强度、二氧化碳浓度、温度或水分中的任意两个"},
                ),
            ],
        ),
        (
            Quiz(
                title="水循环形成性测验",
                class_id=earth_science.id,
                status="generated",
                style_profile={"grade_level": "八年级", "question_count": 3},
                generation_metadata=json.dumps(
                    {"provider": "mock", "purpose": "公开演示预置内容"}, ensure_ascii=False
                ),
            ),
            [
                (
                    "mc",
                    "驱动地球水循环的主要能量来源是什么？",
                    {"options": ["太阳", "月球", "地核", "风"], "correct_index": 0},
                ),
                (
                    "tf",
                    "凝结是水蒸气转变为液态水的过程。",
                    {"is_true": True},
                ),
                (
                    "short_answer",
                    "说明城市硬化路面会怎样影响地表径流。",
                    {"answer": "减少下渗并增加地表径流"},
                ),
            ],
        ),
    ]

    for quiz, questions in quizzes:
        session.add(quiz)
        session.flush()
        for order, (question_type, text, data) in enumerate(questions):
            session.add(
                Question(
                    quiz_id=quiz.id,
                    question_type=question_type,
                    text=text,
                    points=1,
                    sort_order=order,
                    data=data,
                )
            )
    session.commit()


def prepare_demo_database(target_path):
    """Build a fresh demo database and atomically replace the runtime copy."""
    if not demo_mode_enabled():
        raise RuntimeError("Refusing to replace a database unless DEMO_MODE=1")
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("DEMO_MODE requires the disposable SQLite database, not DATABASE_URL")

    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.seed")

    # These are exact, private staging paths created only by this bootstrap.
    for path in (staging, Path(f"{staging}-shm"), Path(f"{staging}-wal")):
        path.unlink(missing_ok=True)

    previous_demo_db = os.environ.get("TEACHFLOW_DEMO_DB")
    os.environ["TEACHFLOW_DEMO_DB"] = str(staging)
    try:
        if not setup_demo_data():
            raise RuntimeError("Could not create the base demo data")
    finally:
        if previous_demo_db is None:
            os.environ.pop("TEACHFLOW_DEMO_DB", None)
        else:
            os.environ["TEACHFLOW_DEMO_DB"] = previous_demo_db

    engine = get_engine(url=f"sqlite:///{staging.as_posix()}")
    init_db(engine)
    session = get_session(engine)
    try:
        # Migration compatibility may create an empty legacy class. It is not
        # part of the public demo and would make the starting state confusing.
        session.query(Class).filter_by(name=LEGACY_CLASS_NAME).delete()
        session.commit()

        username = os.environ.get("DEMO_USERNAME", "teacher")
        password = os.environ.get("DEMO_PASSWORD", "teacher123")
        if len(password) < 8:
            raise RuntimeError("DEMO_PASSWORD must contain at least 8 characters")
        create_user(session, username, password, display_name="TeachFlow 演示教师", role="teacher")
        _seed_quizzes(session)
    finally:
        session.close()
        engine.dispose()

    # A stopped SQLite process can leave WAL sidecars behind. Remove only the
    # exact sidecars for this explicitly configured demo target before the
    # atomic replacement so writes from a previous demo cannot be replayed.
    for path in (Path(f"{target}-shm"), Path(f"{target}-wal")):
        path.unlink(missing_ok=True)
    staging.replace(target)
    print(f"[OK] Disposable demo database prepared at {target}")


def main():
    if not demo_mode_enabled():
        print("[OK] DEMO_MODE is disabled; keeping the configured database unchanged")
        return 0

    database_path = os.environ.get("DATABASE_PATH")
    if not database_path:
        print("[ERROR] Demo database initialization failed: DATABASE_PATH is required", file=sys.stderr)
        return 1

    try:
        prepare_demo_database(database_path)
    except Exception as exc:
        print(f"[ERROR] Demo database initialization failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
