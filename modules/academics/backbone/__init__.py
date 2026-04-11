"""
Academic backbone models (class offerings, enrollments, bell schedules, timetable versions, attendance sessions).

PHASE 2 CLEANUP (TODO): Remove deprecated parallel tables subject_load, timetable_slots, legacy attendance
after all services read/write the new models.
"""

from modules.academics.backbone.models import (  # noqa: F401
    AcademicSettings,
    AcademicTerm,
    AttendanceRecord,
    AttendanceSession,
    BellSchedule,
    BellSchedulePeriod,
    ClassSubjectTeacher,
    ClassTeacherAssignment,
    StudentClassEnrollment,
    TimetableEntry,
    TimetableVersion,
)
