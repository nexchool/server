"""GraphQL fields for a class's week.

The timetable is an optional module, so these carry the feature gate.

`requires_any(read, manage)` lets both a reader and an editor reach the
field; how much each one gets is the resolver's business, exactly as in REST:
somebody without `timetable.manage` is served in reader mode, which trims the
draft machinery out of the answer. The guard answers "may this run", never
"how much of it".

The REST routes stay — the Expo client reads both of these
(`client/modules/academics/api/classAcademicApi.ts`) — and both transports
call the same `timetable_v2` service, so they cannot drift.
"""

from __future__ import annotations

from typing import List, Optional

import strawberry

from graphql_api.errors import ValidationError
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    requires_any,
    requires_feature,
)

from .graphql.timetable_types import (
    Timetable,
    TimetableVersion,
    bundle_to_graphql,
    version_to_graphql,
)

PERM_READ = "timetable.read"
PERM_MANAGE = "timetable.manage"

READS = [
    IsAuthenticated,
    RequiresTenant,
    requires_feature("timetable"),
    requires_any(PERM_READ, PERM_MANAGE),
]


@strawberry.type
class TimetableQuery:
    @strawberry.field(
        permission_classes=READS,
        description=(
            "The timetables drafted or published for a class. Pass "
            "`includeDrafts` to see the ones not in use yet."
        ),
    )
    def timetable_versions(
        self,
        info: strawberry.Info,
        class_id: strawberry.ID,
        include_drafts: bool = True,
    ) -> List[TimetableVersion]:
        from modules.academics.services import timetable_v2

        result = timetable_v2.list_versions(
            info.context.tenant_id, str(class_id), include_drafts=include_drafts
        )
        if not result.get("success"):
            raise ValidationError(result.get("error") or "Could not read the timetable")
        return [version_to_graphql(row) for row in result.get("items", [])]

    @strawberry.field(
        permission_classes=READS,
        description=(
            "One class's week, with everything needed to draw it: the "
            "version, the bell schedule, the days the school opens and the "
            "lessons. Omit `versionId` for the one in use."
        ),
    )
    def timetable(
        self,
        info: strawberry.Info,
        class_id: strawberry.ID,
        version_id: Optional[strawberry.ID] = None,
    ) -> Timetable:
        from modules.academics.services import timetable_v2
        from modules.rbac.services import has_permission

        # Same rule the route applies: somebody who cannot manage timetables
        # is served the reader's view.
        reader_mode = not has_permission(info.context.current_user.id, PERM_MANAGE)
        result = timetable_v2.list_entries_for_active_or_draft(
            info.context.tenant_id,
            str(class_id),
            version_id=str(version_id) if version_id else None,
            reader_mode=reader_mode,
        )
        if not result.get("success"):
            raise ValidationError(result.get("error") or "Could not read the timetable")
        return bundle_to_graphql(result)
