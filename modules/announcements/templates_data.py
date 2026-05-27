"""Baked-in announcement templates (read-only). 5 system templates."""

SYSTEM_TEMPLATES = [
    {
        "id": "school_closure",
        "title": "School closure",
        "body_markdown": (
            "**School will remain closed on [DATE]** due to [REASON].\n\n"
            "Classes will resume on [NEXT_DATE]. Please make alternative arrangements "
            "for any commitments planned for that day.\n\n"
            "For urgent queries, contact the school office."
        ),
    },
    {
        "id": "exam_reminder",
        "title": "Exam reminder",
        "body_markdown": (
            "**[EXAM_NAME] begins on [DATE]**\n\n"
            "Please ensure:\n"
            "- Hall ticket is ready and signed by parents\n"
            "- Arrive 15 minutes before the start time\n"
            "- Carry only permitted stationery\n\n"
            "Wishing all students the very best."
        ),
    },
    {
        "id": "parent_meeting",
        "title": "Parent–teacher meeting",
        "body_markdown": (
            "Dear parents,\n\n"
            "A parent–teacher meeting is scheduled for **[DATE]** at **[TIME]**. "
            "We look forward to discussing your child's progress.\n\n"
            "Please confirm your attendance by replying to your class teacher."
        ),
    },
    {
        "id": "fee_due",
        "title": "Fee due reminder",
        "body_markdown": (
            "**Friendly reminder:** Fees for [TERM] are due by [DUE_DATE].\n\n"
            "Please make payment via the school portal or at the office to avoid late fees. "
            "Receipts are available immediately after payment."
        ),
    },
    {
        "id": "weather_alert",
        "title": "Weather alert",
        "body_markdown": (
            "**Weather advisory: [BRIEF]**\n\n"
            "The school will [REMAIN OPEN / BE CLOSED / DISMISS EARLY] today. "
            "Please track this announcement for updates. Stay safe."
        ),
    },
]
