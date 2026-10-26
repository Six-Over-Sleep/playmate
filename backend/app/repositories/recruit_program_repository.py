"""신규 모임의 ORM 접근과 잠금. 서비스는 이 모듈을 통해서만 DB를 사용한다."""

from dataclasses import asdict, fields
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    exists,
    func,
    inspect,
    literal,
    or_,
    select,
)

from backend.app.domain.recruit_program import Application, PolicyError, Program
from backend.app.models.member import Member
from backend.app.models.post import Post
from backend.app.models.post_like import PostLike
from backend.app.models.post_scrap import PostScrap
from backend.app.models.recruit import Recruit, RecruitMember, RecruitStudyDetail
from backend.app.models.recruit_program import (
    ActivityRecord,
    ApplicationRecord,
    CommandRecord,
    CurriculumRecord,
    EligibilityRecord,
    OutboxRecord,
    ProgramRecord,
    RecognitionRecord,
    WithdrawalRecord,
)


def utc(value):
    """저장 시 UTC인 컬럼을 SQLite 테스트에서도 같은 기준으로 복원한다."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class ProgramRepository:
    def __init__(self, session):
        self.session = session
        self._schema_ready = None

    def schema_available(self):
        """요청 범위에서만 메타데이터 준비 여부를 캐시한다. 기존 DB에 테이블을 만들지 않는다."""
        if self._schema_ready is None:
            schema = (
                self.session.get_bind()
                .get_execution_options()
                .get("schema_translate_map", {})
                .get(None)
            )
            self._schema_ready = inspect(self.session.connection()).has_table(
                "recruit_programs", schema=schema
            )
        return self._schema_ready

    def is_program(self, recruit_id):
        """마이그레이션 전 기존 DB도 읽을 수 있게 테이블 존재를 확인한 뒤 분기한다."""
        if not self.schema_available():
            return False
        return (
            self.session.scalar(
                select(ProgramRecord.recruit_id).where(
                    ProgramRecord.recruit_id == recruit_id
                )
            )
            is not None
        )

    def program_ids(self):
        """비활성화 상태에서도 신규 행이 기존 쓰기 경로로 우회되지 않게 식별한다."""
        if not self.schema_available():
            return set()
        return set(self.session.scalars(select(ProgramRecord.recruit_id)).all())

    @staticmethod
    def visible_post():
        """기존 게시글의 두 논리 삭제 표식을 모두 확인한다."""
        return and_(
            Post.deleted_at.is_(None),
            or_(Post.post_status != "DELETED", Post.post_status.is_(None)),
        )

    def actor(self, member_id, lock=False):
        """실제 활성 회원과 서버 관리자 권한을 조회하고 필요 시 회원 행을 잠근다."""
        if member_id <= 0:
            raise PolicyError("실제 로그인 회원이 필요합니다.", 403)
        query = select(Member).where(Member.member_id == member_id)
        if lock:
            query = query.with_for_update()
        member = self.session.scalar(query)
        if member is None or member.member_status != "ACTIVE":
            raise PolicyError("활성 회원으로 로그인해주세요.", 403)
        return member.role_code == "ADMIN"

    def restricted(self, member_id):
        """누적 이탈 3회 여부만 조회한다. 기존 유효 신청의 승격을 막는 데 사용하지 않는다."""
        return self.eligibility_info(member_id)["is_restricted"]

    def eligibility_info(self, member_id):
        """본인에게만 공개할 누적 이탈·제한 발효 정보를 반환한다."""
        state = (
            self.session.get(EligibilityRecord, member_id)
            if member_id is not None
            else None
        )
        count = state.withdrawal_count if state else 0
        return {
            "withdrawal_count": count,
            "is_restricted": count >= 3,
            "reason_code": "THREE_WITHDRAWALS" if count >= 3 else None,
            "restricted_at": (
                utc(state.restricted_at).isoformat()
                if state and state.restricted_at
                else None
            ),
        }

    def load(self, recruit_id, lock=False):
        """모임과 신청 행을 복원한다. 쓰기에서는 동일 모임 변경을 행 잠금으로 직렬화한다."""
        query = (
            select(ProgramRecord)
            .join(Recruit, Recruit.recruit_id == ProgramRecord.recruit_id)
            .join(Post, Post.post_id == Recruit.post_id)
            .where(ProgramRecord.recruit_id == recruit_id, self.visible_post())
        )
        if lock:
            query = query.with_for_update(of=ProgramRecord).execution_options(
                populate_existing=True
            )
        record = self.session.scalar(query)
        if record is None:
            raise PolicyError("신규 프로젝트·스터디를 찾을 수 없습니다.", 404)
        rows = self.session.scalars(
            select(ApplicationRecord)
            .where(ApplicationRecord.recruit_id == recruit_id)
            .order_by(ApplicationRecord.sequence)
        ).all()
        return self.hydrate(record, rows)

    @staticmethod
    def hydrate(record, rows):
        """이미 조회한 행으로 복원한다. 목록에서도 모임별 추가 SELECT를 발생시키지 않는다."""
        data = dict(record.payload)
        data.update(
            recruit_id=record.recruit_id,
            starts_at=utc(record.starts_at),
            ends_at=utc(record.ends_at),
            schedule_version=record.schedule_version,
            lifecycle_status=record.lifecycle_status,
        )
        program = Program(**data)
        for row in rows:
            values = dict(row.payload)
            changed = values.get("changed_at")
            values["changed_at"] = datetime.fromisoformat(changed) if changed else None
            program.applications.append(
                Application(
                    member_id=row.member_id,
                    sequence=row.sequence,
                    submitted_at=utc(row.submitted_at),
                    status=row.status,
                    application_id=row.application_id,
                    **values,
                )
            )
        return program

    def list_programs(self, base_rows, member_id):
        """기존 목록 집계를 재사용하고 확정자/본인 대기 신청의 필요한 컬럼만 읽는다.

        취소 이력과 커리어 JSON 전체를 목록에 적재하지 않는다. 대기 인원은 DB에서 집계한다.
        """
        bases = {
            row["recruit_id"]: row
            for row in base_rows
            if row["category"] in {"project", "study"}
        }
        if not bases:
            return []
        ids = list(bases)
        waiting = (
            select(ApplicationRecord.recruit_id, func.count().label("waiting_count"))
            .where(
                ApplicationRecord.recruit_id.in_(ids),
                ApplicationRecord.status == "WAITING",
            )
            .group_by(ApplicationRecord.recruit_id)
            .subquery()
        )
        rows = self.session.execute(
            select(ProgramRecord, Recruit, func.coalesce(waiting.c.waiting_count, 0))
            .join(Recruit, Recruit.recruit_id == ProgramRecord.recruit_id)
            .outerjoin(waiting, waiting.c.recruit_id == ProgramRecord.recruit_id)
            .where(ProgramRecord.recruit_id.in_(ids))
        ).all()
        programs = {
            record.recruit_id: self.hydrate(record, []) for record, _, _ in rows
        }
        if not programs:
            return []
        visible = ApplicationRecord.status == "ACCEPTED"
        if member_id is not None:
            visible = or_(
                visible,
                and_(
                    ApplicationRecord.status == "WAITING",
                    ApplicationRecord.member_id == member_id,
                ),
            )
        applications = self.session.execute(
            select(
                ApplicationRecord.application_id,
                ApplicationRecord.recruit_id,
                ApplicationRecord.member_id,
                ApplicationRecord.sequence,
                ApplicationRecord.submitted_at,
                ApplicationRecord.status,
                ApplicationRecord.payload["skill_ids"].label("skill_ids"),
                ApplicationRecord.payload["leader_volunteer"].label("leader_volunteer"),
            )
            .where(ApplicationRecord.recruit_id.in_(programs), visible)
            .order_by(ApplicationRecord.sequence)
        ).all()
        for row in applications:
            programs[row.recruit_id].applications.append(
                Application(
                    member_id=row.member_id,
                    sequence=row.sequence,
                    submitted_at=utc(row.submitted_at),
                    skill_ids=row.skill_ids or [],
                    leader_volunteer=bool(row.leader_volunteer),
                    status=row.status,
                    application_id=row.application_id,
                )
            )
        post_ids = {record.recruit_id: recruit.post_id for record, recruit, _ in rows}
        reactions = self.member_reactions(list(post_ids.values()), member_id)
        result = []
        for record, recruit, waiting_count in rows:
            program = programs[record.recruit_id]
            basic = {
                **bases[record.recruit_id],
                "post_id": recruit.post_id,
                "place": recruit.place,
                "is_online": recruit.is_online,
                "contact_method": recruit.contact_method,
                **reactions.get(
                    recruit.post_id, {"liked_by_me": False, "scrapped_by_me": False}
                ),
            }
            counts = {
                "participant_count": len(program.accepted()),
                "waiting_count": waiting_count,
            }
            result.append((program, basic, record.details, counts))
        return result

    def member_reactions(self, post_ids, member_id):
        """목록에서 이미 계산한 좋아요 수는 재집계하지 않고 본인의 표시만 일괄 조회한다."""
        if member_id is None or not post_ids:
            return {}
        liked = select(PostLike.post_id, literal("liked_by_me").label("kind")).where(
            PostLike.post_id.in_(post_ids), PostLike.member_id == member_id
        )
        scrapped = select(
            PostScrap.post_id, literal("scrapped_by_me").label("kind")
        ).where(PostScrap.post_id.in_(post_ids), PostScrap.member_id == member_id)
        result = {}
        for post_id, kind in self.session.execute(liked.union_all(scrapped)).all():
            result.setdefault(post_id, {"liked_by_me": False, "scrapped_by_me": False})[
                kind
            ] = True
        return result

    def social_summaries(self, recruit_ids, member_id):
        """기존 좋아요·스크랩 테이블을 재사용해 목록 전체의 집계를 한 번에 조회한다."""
        if not recruit_ids:
            return {}
        scrapped = (
            exists()
            .where(PostScrap.post_id == Post.post_id, PostScrap.member_id == member_id)
            .correlate(Post)
        )
        rows = self.session.execute(
            select(
                Recruit.recruit_id,
                func.count(PostLike.member_id),
                func.max(case((PostLike.member_id == member_id, 1), else_=0)),
                scrapped,
            )
            .join(Post, Post.post_id == Recruit.post_id)
            .outerjoin(PostLike, PostLike.post_id == Post.post_id)
            .where(Recruit.recruit_id.in_(recruit_ids))
            .group_by(Recruit.recruit_id, Post.post_id)
        ).all()
        return {
            row[0]: {
                "like_count": row[1],
                "liked_by_me": member_id is not None and bool(row[2]),
                "scrapped_by_me": bool(row[3]),
            }
            for row in rows
        }

    def member_names(self, member_ids):
        """기존 회원 닉네임을 일괄 조회한다. 별도의 회원 복사본을 만들지 않는다."""
        return (
            dict(
                self.session.execute(
                    select(Member.member_id, Member.nickname).where(
                        Member.member_id.in_(member_ids)
                    )
                ).all()
            )
            if member_ids
            else {}
        )

    def create(self, program, data, now):
        """기존 게시글/모임에 신규 프로그램을 연결한다. 저장 확정은 서비스가 결정한다."""
        post = Post(
            author_member_id=program.creator_id,
            title=data.title,
            body=data.body,
            post_type="RECRUIT",
            post_status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        self.session.add(post)
        self.session.flush()
        recruit = Recruit(
            post_id=post.post_id,
            category=program.category,
            recruit_mode=data.recruit_mode,
            capacity=program.capacity,
            state="OPEN",
            created_at=now,
            updated_at=now,
            place=data.place,
            is_online=data.is_online,
            contact_method=data.contact_method,
        )
        self.session.add(recruit)
        self.session.flush()
        program.recruit_id = recruit.recruit_id
        self.save(program)
        return {"recruit_id": recruit.recruit_id, "post_id": post.post_id}

    def save(self, program):
        """일정·신청·외부 전달 요청을 호출자의 단일 트랜잭션에 저장한다."""
        record = self.session.get(ProgramRecord, program.recruit_id)
        if record is None:
            record = ProgramRecord(recruit_id=program.recruit_id)
            self.session.add(record)
        excluded = {
            "starts_at",
            "ends_at",
            "recruit_id",
            "applications",
            "application_changes",
            "events",
            "schedule_version",
            "lifecycle_status",
        }
        record.payload = {
            item.name: getattr(program, item.name)
            for item in fields(program)
            if item.name not in excluded
        }
        record.starts_at, record.ends_at = program.starts_at, program.ends_at
        record.schedule_version = program.schedule_version
        record.lifecycle_status = program.lifecycle_status
        recruit = self.session.get(Recruit, program.recruit_id)
        recruit.capacity = program.capacity
        # 기존 모임/봇 컬럼은 KST naive, 신규 프로그램 컬럼은 시간대 포함 UTC다.
        # UTC의 tzinfo만 지우면 기존 봇의 마감 판단이 9시간 어긋난다.
        seoul = ZoneInfo("Asia/Seoul")
        recruit.deadline_at = program.deadline_at.astimezone(seoul).replace(tzinfo=None)
        if recruit.recruit_mode == "short":
            recruit.meeting_start = program.starts_at.astimezone(seoul).replace(
                tzinfo=None
            )
            recruit.meeting_end = program.ends_at.astimezone(seoul).replace(tzinfo=None)
        recruit.state = (
            "OPEN" if program.lifecycle_status in {"RECRUITING", "READY"} else "CLOSED"
        )
        recruit.close_reason = program.termination_reason
        self.session.flush()
        changes = dict(program.application_changes)
        changes.update(
            {
                item.sequence: item
                for item in program.applications
                if item.application_id is None
            }
        )
        changed = sorted(changes.values(), key=lambda item: item.sequence)
        self.save_applications(program.recruit_id, changed)
        if changed:
            self.sync_legacy_members(program, changed)
        program.application_changes.clear()
        for event in program.events:
            self.enqueue(
                program.recruit_id,
                event["kind"],
                event["key"],
                event["payload"],
                event["schedule_version"],
            )
        program.events.clear()

    def save_applications(self, recruit_id, changed):
        """변경된 신청만 읽고 저장한다. 기존 취소 확정 후 새 행을 넣어 유일 인덱스를 지킨다."""
        if not changed:
            return
        ids = [
            item.application_id for item in changed if item.application_id is not None
        ]
        saved = (
            {
                row.application_id: row
                for row in self.session.scalars(
                    select(ApplicationRecord).where(
                        ApplicationRecord.application_id.in_(ids)
                    )
                ).all()
            }
            if ids
            else {}
        )
        # 기존 상태를 먼저 반영해야 취소 후 재신청이 부분 유일 인덱스와 충돌하지 않는다.
        for item in changed:
            if item.application_id:
                saved[item.application_id].status = item.status
        if ids:
            self.session.flush()
        written = []
        for item in changed:
            row = saved.get(item.application_id)
            if row is None:
                row = ApplicationRecord(recruit_id=recruit_id)
                self.session.add(row)
            values = asdict(item)
            row.member_id, row.sequence = item.member_id, item.sequence
            row.submitted_at, row.status = item.submitted_at, item.status
            for key in (
                "member_id",
                "sequence",
                "submitted_at",
                "status",
                "application_id",
            ):
                values.pop(key)
            values["changed_at"] = (
                item.changed_at.isoformat() if item.changed_at else None
            )
            row.payload = values
            written.append((item, row))
        self.session.flush()
        for item, row in written:
            item.application_id = row.application_id

    def sync_legacy_members(self, program, changed):
        """기존 마이페이지·봇 조회용 JOINED 기록을 확정 참여자에만 맞춘다.

        새 신청/대기/팀장 상태는 신규 테이블이 원본이다. 기존 모임 데이터는 변경하지 않는다.
        """
        saved = {
            row.member_id: row
            for row in self.session.scalars(
                select(RecruitMember).where(
                    RecruitMember.recruit_id == program.recruit_id,
                    RecruitMember.member_id.in_({item.member_id for item in changed}),
                )
            ).all()
        }
        latest = {item.member_id: item for item in changed}
        for member_id, item in latest.items():
            row = saved.get(member_id)
            if row is None and item.status != "ACCEPTED":
                continue
            if row is None:
                row = RecruitMember(recruit_id=program.recruit_id, member_id=member_id)
                self.session.add(row)
            changed_at = (
                (item.changed_at or item.submitted_at)
                .astimezone(ZoneInfo("Asia/Seoul"))
                .replace(tzinfo=None)
            )
            row.role = (
                "HOST"
                if program.creator_type == "USER" and member_id == program.creator_id
                else "MEMBER"
            )
            row.status = "JOINED" if item.status == "ACCEPTED" else "CANCELED"
            if item.status == "ACCEPTED":
                row.joined_at, row.canceled_at = changed_at, None
            else:
                row.canceled_at = changed_at
            row.updated_at = changed_at

    def enqueue(self, recruit_id, kind, key, payload, version=None):
        """모임으로 범위를 제한한 유일 키로 외부 요청을 예약하고 실제 전송은 하지 않는다."""
        event_key = f"recruit:{recruit_id}:{key}"
        if self.session.get(OutboxRecord, event_key) is None:
            self.session.add(
                OutboxRecord(
                    event_key=event_key,
                    recruit_id=recruit_id,
                    kind=kind,
                    payload={
                        "recruit_id": recruit_id,
                        "schedule_version": version,
                        **payload,
                    },
                    schedule_version=version,
                )
            )
            self.session.flush()

    def record_departure(self, program, member_id, application, now):
        """회원 행 잠금을 선행한다. 서로 다른 모임의 동시 이탈도 같은 회원에서 직렬화한다."""
        key = f"recruit:{program.recruit_id}:application:{application.sequence}:left"
        if self.session.get(WithdrawalRecord, key):
            return
        state = self.session.get(EligibilityRecord, member_id)
        if state is None:
            state = EligibilityRecord(member_id=member_id, withdrawal_count=0)
            self.session.add(state)
        state.withdrawal_count += 1
        if state.withdrawal_count >= 3 and state.restricted_at is None:
            state.restricted_at = now
        self.session.add(
            WithdrawalRecord(
                event_key=key,
                recruit_id=program.recruit_id,
                member_id=member_id,
                occurred_at=now,
            )
        )

    def command(self, recruit_id, key):
        """연장 재시도의 원 요청과 응답을 조회한다. 비교 판단은 서비스에서 수행한다."""
        return self.session.get(CommandRecord, (recruit_id, key))

    def metadata(self, recruit_id):
        """스터디 종류·난이도·정기 일정 등 프로그램 상세 저장값을 반환한다."""
        return self.session.get(ProgramRecord, recruit_id).details

    def basic_detail(self, recruit_id):
        """기존 게시글과 모임 필드를 읽어 응답 계약을 유지한다."""
        recruit = self.session.get(Recruit, recruit_id)
        post = self.session.get(Post, recruit.post_id)
        return self.basic_values(recruit, post)

    @staticmethod
    def basic_values(recruit, post):
        """목록/상세에서 공통으로 사용하는 기존 컬럼만 직렬화한다."""
        return {
            "title": post.title,
            "body": post.body,
            "post_id": post.post_id,
            "view_count": post.view_count,
            "state": recruit.state,
            "recruit_mode": recruit.recruit_mode,
            "place": recruit.place,
            "is_online": recruit.is_online,
            "contact_method": recruit.contact_method,
        }

    def set_metadata(self, recruit_id, details):
        """프로그램 상세와 기존 정기 일정/스터디 상세를 같은 트랜잭션에서 맞춘다."""
        self.session.get(ProgramRecord, recruit_id).details = details
        recruit = self.session.get(Recruit, recruit_id)
        if recruit.recruit_mode == "regular":
            recruit.regular_days = details.get("regular_days")
            recruit.regular_time = time.fromisoformat(details["regular_time"])
            recruit.regular_start_date = date.fromisoformat(
                details["regular_start_date"]
            )
        if recruit.category == "study":
            row = self.session.get(RecruitStudyDetail, recruit_id)
            if row is None:
                row = RecruitStudyDetail(recruit_id=recruit_id)
                self.session.add(row)
            row.study_topic = details.get("study_topic")
            row.study_period = details.get("study_period")
            row.study_method = details.get("study_method")

    def store_command(self, recruit_id, member_id, key, request, response):
        """중복 방지 키를 회원·원 요청·원 결과와 함께 영속 저장한다."""
        self.session.add(
            CommandRecord(
                recruit_id=recruit_id,
                member_id=member_id,
                request_key=key,
                request=request,
                response=response,
            )
        )

    def edit(self, program, changes, now):
        """서비스가 허용한 표시 필드만 적용하며 미전달 필드를 덮어쓰지 않는다."""
        recruit = self.session.get(Recruit, program.recruit_id)
        post = self.session.get(Post, recruit.post_id)
        for key, value in changes.items():
            if key in {"title", "body"}:
                if value is None:
                    raise PolicyError("제목·설명은 비울 수 없습니다.", 422)
                setattr(post, key, value)
            else:
                recruit.contact_method = value
        post.updated_at = now

    def archive(self, recruit_id, now):
        """참여 이력은 보존하고 연결 게시글만 기존 방식으로 논리 삭제한다."""
        recruit = self.session.get(Recruit, recruit_id)
        post = self.session.get(Post, recruit.post_id)
        post.post_status = "DELETED"
        post.deleted_at = now.astimezone(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)

    def curriculum(self, recruit_id):
        """저장 전 빈 초안도 버전 1로 표현해 최초 저장과 버전 충돌을 일관되게 처리한다."""
        row = self.session.get(CurriculumRecord, recruit_id)
        return (
            {"version": row.version, "items": row.items}
            if row
            else {"version": 1, "items": []}
        )

    def save_curriculum(self, recruit_id, version, items):
        """모임 행 잠금 안에서 현재 버전을 확인하고 다음 버전으로 저장한다."""
        current = self.curriculum(recruit_id)
        if current["version"] != version:
            raise PolicyError("다른 사용자가 수정했습니다. 최신 버전을 확인해주세요.")
        row = self.session.get(CurriculumRecord, recruit_id)
        if row is None:
            row = CurriculumRecord(recruit_id=recruit_id)
            self.session.add(row)
        row.version, row.items = version + 1, items
        return {"version": row.version, "items": items}

    def add_activity(self, recruit_id, member_id, data, now):
        """활동 입력을 저장하고 ID/작성자/시각을 포함한 계약 객체를 반환한다."""
        row = ActivityRecord(
            recruit_id=recruit_id,
            author_member_id=member_id,
            created_at=now,
            payload=data,
        )
        self.session.add(row)
        self.session.flush()
        return {
            "activity_id": row.activity_id,
            "recruit_id": recruit_id,
            "author_member_id": member_id,
            "created_at": now.isoformat(),
            **data,
        }

    def activities(self, recruit_id):
        """해당 모임 활동만 ID 순서로 조회한다. 활동 인정/보상 정보를 임의 합산하지 않는다."""
        return [
            {
                "activity_id": row.activity_id,
                "recruit_id": recruit_id,
                "author_member_id": row.author_member_id,
                "created_at": utc(row.created_at).isoformat(),
                **row.payload,
            }
            for row in self.session.scalars(
                select(ActivityRecord)
                .where(ActivityRecord.recruit_id == recruit_id)
                .order_by(ActivityRecord.activity_id)
            ).all()
        ]

    def pending_ids(self, now):
        """마감·시작·종료가 도래한 모임만 조회한다. 처리한 마감은 같은 버전에서 재처리하지 않는다."""
        prepare_key = (
            literal("recruit:")
            + cast(ProgramRecord.recruit_id, String)
            + literal(":discord:")
            + cast(ProgramRecord.schedule_version, String)
        )
        prepared = (
            exists()
            .where(OutboxRecord.event_key == prepare_key)
            .correlate(ProgramRecord)
        )
        waiting = ProgramRecord.lifecycle_status.in_(["RECRUITING", "READY"])
        due = or_(
            and_(
                ProgramRecord.lifecycle_status == "IN_PROGRESS",
                ProgramRecord.ends_at <= now,
            ),
            and_(waiting, ProgramRecord.starts_at <= now),
            and_(
                waiting, ProgramRecord.starts_at <= now + timedelta(hours=24), ~prepared
            ),
        )
        return list(
            self.session.scalars(
                select(ProgramRecord.recruit_id)
                .join(Recruit, Recruit.recruit_id == ProgramRecord.recruit_id)
                .join(Post, Post.post_id == Recruit.post_id)
                .where(
                    self.visible_post(),
                    due,
                )
            ).all()
        )

    def activity(self, activity_id):
        """개인 인정의 원본 활동을 조회한다. 다른 모임 자료인지 서비스에서 검사한다."""
        return self.session.get(ActivityRecord, activity_id)

    def recognition(self, key):
        """동일 개인/활동/인정 종류의 기존 판정 근거를 조회한다."""
        return self.session.get(RecognitionRecord, key)

    def save_recognition(self, key, recruit_id, member_id, activity_id, payload):
        """회원별 인정 근거를 기록한다. XP 총액과 레벨은 저장하지 않는다."""
        self.session.add(
            RecognitionRecord(
                recognition_key=key,
                recruit_id=recruit_id,
                member_id=member_id,
                activity_id=activity_id,
                payload=payload,
            )
        )
        self.session.flush()

    def pending_events(self, kinds):
        """미전달 사건 키만 조회하고 각 사건은 처리 직전에 다시 잠가 확인한다."""
        return list(
            self.session.execute(
                select(OutboxRecord.event_key, OutboxRecord.recruit_id)
                .join(Recruit, Recruit.recruit_id == OutboxRecord.recruit_id)
                .join(Post, Post.post_id == Recruit.post_id)
                .where(
                    OutboxRecord.status == "PENDING",
                    OutboxRecord.kind.in_(kinds),
                    self.visible_post(),
                )
                .order_by(OutboxRecord.event_key)
            ).all()
        )

    def reward_delivered(self, event, payload, reference):
        """전달 참조를 개인 인정 기록에 연결한다. 회원 잔액/레벨은 변경하지 않는다."""
        if event.kind == "XP_GRANT":
            key = payload["recognition_key"]
            record = self.recognition(key)
            if record is not None:
                record.payload = {
                    **record.payload,
                    "reward_status": "GRANTED",
                    "grant_reference": reference,
                }
        elif event.kind == "XP_REVOKE":
            original = self.event(payload["original_event_key"])
            record = self.recognition(original.payload["recognition_key"])
            if record is not None:
                record.payload = {
                    **record.payload,
                    "reward_status": "REVOKED",
                    "revoke_reference": reference,
                }

    def event(self, key):
        """지정한 원 지급 사건을 조회해 정확한 회수 참조를 구성한다."""
        return self.session.get(OutboxRecord, key)

    def lock_event(self, key):
        """다른 worker가 완료한 상태까지 새로 읽어 중복 전달을 줄인다."""
        return self.session.scalar(
            select(OutboxRecord)
            .where(OutboxRecord.event_key == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
