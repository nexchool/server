"""
Seed default subject templates for the school setup wizard.

Run once: python scripts/seed_subject_templates.py
Idempotent: skips existing board_codes.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from core.database import db
from modules.school_setup.template_models import SubjectTemplateGroup, SubjectTemplateItem

TEMPLATES = {
    "cbse": {
        "name": "CBSE Standard Template",
        "items": [
            *[{"grade": g, "stream": None, "subjects": [
                ("English", "ENG", 6, False),
                ("Hindi", "HIN", 5, False),
                ("Mathematics", "MATH", 6, False),
                ("Environmental Studies", "EVS", 4, False),
            ]} for g in range(1, 3)],
            *[{"grade": g, "stream": None, "subjects": [
                ("English", "ENG", 6, False),
                ("Hindi", "HIN", 5, False),
                ("Mathematics", "MATH", 6, False),
                ("Environmental Studies", "EVS", 4, False),
            ]} for g in range(3, 6)],
            *[{"grade": g, "stream": None, "subjects": [
                ("English", "ENG", 6, False),
                ("Hindi", "HIN", 5, False),
                ("Mathematics", "MATH", 6, False),
                ("Science", "SCI", 6, False),
                ("Social Science", "SST", 5, False),
                ("Sanskrit", "SAN", 4, True),
            ]} for g in range(6, 9)],
            *[{"grade": g, "stream": None, "subjects": [
                ("English Language & Literature", "ENG", 6, False),
                ("Hindi", "HIN", 5, False),
                ("Mathematics", "MATH", 6, False),
                ("Science", "SCI", 6, False),
                ("Social Science", "SST", 5, False),
                ("IT / Computer Applications", "IT", 4, True),
            ]} for g in range(9, 11)],
            *[{"grade": g, "stream": "Science", "subjects": [
                ("English Core", "ENG", 5, False),
                ("Physics", "PHY", 6, False),
                ("Chemistry", "CHEM", 6, False),
                ("Mathematics", "MATH", 6, False),
                ("Biology", "BIO", 6, True),
                ("Computer Science", "CS", 4, True),
                ("Physical Education", "PE", 2, True),
            ]} for g in range(11, 13)],
            *[{"grade": g, "stream": "Commerce", "subjects": [
                ("English Core", "ENG", 5, False),
                ("Accountancy", "ACC", 6, False),
                ("Business Studies", "BST", 6, False),
                ("Economics", "ECO", 6, False),
                ("Mathematics", "MATH", 6, True),
                ("Physical Education", "PE", 2, True),
            ]} for g in range(11, 13)],
            *[{"grade": g, "stream": "Arts", "subjects": [
                ("English Core", "ENG", 5, False),
                ("History", "HIST", 6, False),
                ("Political Science", "POL", 6, False),
                ("Geography", "GEO", 5, False),
                ("Economics", "ECO", 5, True),
                ("Sociology", "SOC", 5, True),
                ("Physical Education", "PE", 2, True),
            ]} for g in range(11, 13)],
        ],
    },
    "gujarat_state_board": {
        "name": "Gujarat State Board (GSEB) Template",
        "items": [
            *[{"grade": g, "stream": None, "subjects": [
                ("Gujarati", "GUJ", 6, False),
                ("English", "ENG", 5, False),
                ("Hindi", "HIN", 4, False),
                ("Mathematics", "MATH", 6, False),
                ("Paryavaran (EVS)", "EVS", 4, False),
            ]} for g in range(1, 6)],
            *[{"grade": g, "stream": None, "subjects": [
                ("Gujarati", "GUJ", 6, False),
                ("English", "ENG", 5, False),
                ("Hindi", "HIN", 4, False),
                ("Mathematics", "MATH", 6, False),
                ("Science & Technology", "SCI", 6, False),
                ("Social Science", "SST", 5, False),
                ("Sanskrit", "SAN", 3, True),
            ]} for g in range(6, 9)],
            *[{"grade": g, "stream": None, "subjects": [
                ("Gujarati", "GUJ", 6, False),
                ("English (FL)", "ENG", 5, False),
                ("Hindi (SL)", "HIN", 4, False),
                ("Mathematics", "MATH", 6, False),
                ("Science & Technology", "SCI", 6, False),
                ("Social Science", "SST", 5, False),
            ]} for g in range(9, 11)],
            *[{"grade": g, "stream": "Science", "subjects": [
                ("English", "ENG", 4, False),
                ("Gujarati", "GUJ", 3, False),
                ("Physics", "PHY", 6, False),
                ("Chemistry", "CHEM", 6, False),
                ("Mathematics", "MATH", 6, False),
                ("Biology", "BIO", 6, True),
            ]} for g in range(11, 13)],
            *[{"grade": g, "stream": "Commerce", "subjects": [
                ("English", "ENG", 4, False),
                ("Gujarati", "GUJ", 3, False),
                ("Accountancy & Auditing", "ACC", 6, False),
                ("Organisation of Commerce", "ORG", 5, False),
                ("Economics", "ECO", 5, False),
                ("Statistics", "STAT", 5, True),
            ]} for g in range(11, 13)],
            *[{"grade": g, "stream": "Arts", "subjects": [
                ("English", "ENG", 4, False),
                ("Gujarati", "GUJ", 4, False),
                ("History", "HIST", 5, False),
                ("Geography", "GEO", 5, False),
                ("Economics", "ECO", 5, False),
                ("Psychology", "PSY", 5, True),
                ("Sociology", "SOC", 5, True),
            ]} for g in range(11, 13)],
        ],
    },
    "icse": {
        "name": "ICSE / ISC Template",
        "items": [
            *[{"grade": g, "stream": None, "subjects": [
                ("English Language", "ENG", 7, False),
                ("Mathematics", "MATH", 6, False),
                ("Environmental Education", "EVS", 4, False),
                ("Second Language (Hindi/Regional)", "L2", 4, False),
            ]} for g in range(1, 6)],
            *[{"grade": g, "stream": None, "subjects": [
                ("English Language", "ENGL", 6, False),
                ("English Literature", "ENGLIT", 4, False),
                ("Mathematics", "MATH", 6, False),
                ("History & Civics", "HIST", 4, False),
                ("Geography", "GEO", 4, False),
                ("Science (Physics/Chemistry/Biology)", "SCI", 6, False),
                ("Second Language (Hindi)", "HIN", 4, False),
                ("Computer Applications", "COMP", 3, True),
            ]} for g in range(6, 9)],
            *[{"grade": g, "stream": None, "subjects": [
                ("English Language", "ENGL", 6, False),
                ("English Literature", "ENGLIT", 4, False),
                ("Mathematics", "MATH", 6, False),
                ("History & Civics", "HIST", 4, False),
                ("Geography", "GEO", 4, False),
                ("Physics", "PHY", 5, False),
                ("Chemistry", "CHEM", 5, False),
                ("Biology", "BIO", 5, False),
                ("Second Language (Hindi)", "HIN", 4, False),
            ]} for g in range(9, 11)],
            *[{"grade": g, "stream": "Science", "subjects": [
                ("English", "ENG", 5, False),
                ("Physics", "PHY", 6, False),
                ("Chemistry", "CHEM", 6, False),
                ("Mathematics", "MATH", 6, False),
                ("Biology", "BIO", 6, True),
                ("Computer Science", "CS", 4, True),
            ]} for g in range(11, 13)],
            *[{"grade": g, "stream": "Commerce", "subjects": [
                ("English", "ENG", 5, False),
                ("Accounts", "ACC", 6, False),
                ("Commerce", "COM", 6, False),
                ("Economics", "ECO", 6, False),
                ("Mathematics", "MATH", 5, True),
            ]} for g in range(11, 13)],
        ],
    },
    "ib": {
        "name": "IB (PYP/MYP/DP) Template",
        "items": [
            *[{"grade": g, "stream": None, "subjects": [
                ("Language A (English)", "LANG_A", 6, False),
                ("Language B (Hindi/Gujarati)", "LANG_B", 4, False),
                ("Mathematics", "MATH", 6, False),
                ("Science", "SCI", 4, False),
                ("Social Studies", "SS", 4, False),
                ("Arts", "ARTS", 3, False),
                ("Physical Education", "PE", 2, False),
            ]} for g in range(1, 6)],
            *[{"grade": g, "stream": None, "subjects": [
                ("Language & Literature (English)", "LANG_LIT", 5, False),
                ("Language Acquisition (Hindi/French)", "LANG_ACQ", 4, False),
                ("Individuals & Societies", "I_S", 5, False),
                ("Sciences", "SCI", 5, False),
                ("Mathematics", "MATH", 6, False),
                ("Arts", "ARTS", 3, False),
                ("Physical & Health Education", "PHE", 2, False),
                ("Design", "DESIGN", 3, False),
            ]} for g in range(6, 11)],
            *[{"grade": g, "stream": None, "subjects": [
                ("Theory of Knowledge", "TOK", 2, False),
                ("Language A: Literature (English)", "LANG_A", 5, False),
                ("Language B (Hindi/French)", "LANG_B", 4, False),
                ("Group 3: History / Economics / Geography", "G3", 5, False),
                ("Group 4: Biology / Chemistry / Physics", "G4", 5, False),
                ("Group 5: Mathematics (AA or AI)", "G5", 5, False),
                ("Group 6: Visual Arts / Music (elective)", "G6", 3, True),
            ]} for g in range(11, 13)],
        ],
    },
}


def seed():
    app = create_app()
    with app.app_context():
        seeded = 0
        skipped = 0
        for board_code, data in TEMPLATES.items():
            existing = SubjectTemplateGroup.query.filter_by(board_code=board_code).first()
            if existing:
                print(f"  SKIP {board_code} — already exists (id={existing.id})")
                skipped += 1
                continue

            group = SubjectTemplateGroup(name=data["name"], board_code=board_code)
            db.session.add(group)
            db.session.flush()  # get group.id

            sort_counters = {}
            for row in data["items"]:
                grade = row["grade"]
                stream = row["stream"]
                for sort_i, (subj_name, subj_code, periods, is_elective) in enumerate(row["subjects"]):
                    key = (grade, stream)
                    sort_counters[key] = sort_counters.get(key, 0)
                    item = SubjectTemplateItem(
                        template_group_id=group.id,
                        grade_number=grade,
                        stream=stream,
                        subject_name=subj_name,
                        subject_code=subj_code,
                        periods_per_week=periods,
                        is_elective=is_elective,
                        sort_order=sort_counters[key],
                    )
                    sort_counters[key] += 1
                    db.session.add(item)

            db.session.commit()
            item_count = SubjectTemplateItem.query.filter_by(template_group_id=group.id).count()
            print(f"  SEED {board_code} — {item_count} subject items created")
            seeded += 1

        print(f"\nDone: {seeded} seeded, {skipped} skipped")


if __name__ == "__main__":
    seed()
