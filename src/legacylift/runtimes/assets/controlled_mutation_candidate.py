"""Engineered guidance-slice candidate used only by the source-mutation gate."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI()
DATABASE = "/state/candidate.sqlite3"


def _connect():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def _now():
    epoch = int(Path("/state/clock").read_text(encoding="utf-8"))
    return datetime.fromtimestamp(epoch, UTC)


def _user(connection, request):
    token = request.headers.get("X-Redmine-API-Key")
    if not token:
        return None
    return connection.execute(
        "SELECT users.* FROM tokens JOIN users ON users.id=tokens.user_id "
        "WHERE tokens.value=? AND tokens.action='api' AND users.status=1 AND users.type='User'",
        (token,),
    ).fetchone()


def _permissions(connection, user_id, project_id):
    rows = connection.execute(
        "SELECT roles.permissions FROM members "
        "JOIN member_roles ON member_roles.member_id=members.id "
        "JOIN roles ON roles.id=member_roles.role_id "
        "WHERE members.user_id=? AND members.project_id=?",
        (user_id, project_id),
    )
    permissions = set()
    for row in rows:
        for line in (row["permissions"] or "").splitlines():
            value = line.strip()
            if value.startswith("- :"):
                permissions.add(value[3:])
    return permissions


def _json_headers():
    return {"Content-Type": "application/json; charset=utf-8"}


def _serialize_issue(connection, issue_id):
    row = connection.execute(
        "SELECT issues.*, projects.name AS project_name, trackers.name AS tracker_name, "
        "statuses.name AS status_name, priorities.name AS priority_name, "
        "users.firstname AS author_firstname, users.lastname AS author_lastname "
        "FROM issues JOIN projects ON projects.id=issues.project_id "
        "JOIN trackers ON trackers.id=issues.tracker_id "
        "JOIN issue_statuses AS statuses ON statuses.id=issues.status_id "
        "LEFT JOIN enumerations AS priorities ON priorities.id=issues.priority_id "
        "AND priorities.type='IssuePriority' "
        "JOIN users ON users.id=issues.author_id WHERE issues.id=?",
        (issue_id,),
    ).fetchone()
    if row is None:
        return None

    def timestamp(value):
        return value.replace(" ", "T") + "Z" if value else None

    return {
        "issue": {
            "author": {
                "id": row["author_id"],
                "name": f"{row['author_firstname']} {row['author_lastname']}".strip(),
            },
            "closed_on": timestamp(row["closed_on"]),
            "created_on": timestamp(row["created_on"]),
            "description": row["description"],
            "done_ratio": row["done_ratio"],
            "due_date": row["due_date"],
            "estimated_hours": row["estimated_hours"],
            "id": row["id"],
            "is_private": bool(row["is_private"]),
            "priority": {"id": row["priority_id"], "name": row["priority_name"]},
            "project": {"id": row["project_id"], "name": row["project_name"]},
            "start_date": row["start_date"],
            "status": {"id": row["status_id"], "name": row["status_name"]},
            "subject": row["subject"],
            "total_estimated_hours": None,
            "tracker": {"id": row["tracker_id"], "name": row["tracker_name"]},
            "updated_on": timestamp(row["updated_on"]),
        }
    }


@app.get("/issues/{issue_id}.json")
def read_issue(issue_id: int, request: Request):
    connection = _connect()
    try:
        user = _user(connection, request)
        issue = connection.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if (
            user is None
            or issue is None
            or "view_issues" not in _permissions(connection, user["id"], issue["project_id"])
        ):
            return Response(
                content=b"",
                status_code=403,
                media_type="application/json",
                headers={"Cache-Control": "no-cache"},
            )
        return JSONResponse(
            _serialize_issue(connection, issue_id),
            status_code=200,
            headers={
                **_json_headers(),
                "Cache-Control": "max-age=0, private, must-revalidate",
            },
        )
    finally:
        connection.close()


@app.post("/issues.json")
async def create_issue(request: Request):
    payload = await request.json()
    issue = payload.get("issue") or {}
    subject = issue.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        return JSONResponse(
            {"errors": ["Subject cannot be blank"]},
            status_code=422,
            headers={
                "Cache-Control": "no-cache",
                "Content-Type": "application/json; charset=utf-8",
            },
        )

    connection = _connect()
    try:
        user = _user(connection, request)
        project_id = issue.get("project_id")
        tracker_id = issue.get("tracker_id")
        if user is None or not project_id or not tracker_id:
            return Response(status_code=403, headers={"Cache-Control": "no-cache"})
        permissions = _permissions(connection, user["id"], project_id)
        tracker = connection.execute(
            "SELECT default_status_id FROM trackers WHERE id=?", (tracker_id,)
        ).fetchone()
        allowed_tracker = connection.execute(
            "SELECT 1 FROM projects_trackers WHERE project_id=? AND tracker_id=?",
            (project_id, tracker_id),
        ).fetchone()
        if "add_issues" not in permissions or tracker is None or allowed_tracker is None:
            return Response(status_code=403, headers={"Cache-Control": "no-cache"})
        priority = connection.execute(
            "SELECT id FROM enumerations WHERE type='IssuePriority' AND is_default=1 "
            "AND active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        now = _now()
        sql_now = now.strftime("%Y-%m-%d %H:%M:%S")
        subject = str(subject)
        # LEGACYLIFT_CREATE_STATE_FAULT_HOOK
        cursor = connection.execute(
            "INSERT INTO issues (tracker_id,project_id,subject,description,status_id,priority_id,"
            "author_id,lock_version,created_on,updated_on,start_date,done_ratio,is_private,"
            "root_id,lft,rgt) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tracker_id,
                project_id,
                subject,
                issue.get("description"),
                tracker["default_status_id"],
                priority["id"] if priority else None,
                user["id"],
                0,
                sql_now,
                sql_now,
                now.strftime("%Y-%m-%d"),
                0,
                0,
                None,
                1,
                2,
            ),
        )
        issue_id = cursor.lastrowid
        connection.execute("UPDATE issues SET root_id=? WHERE id=?", (issue_id, issue_id))
        connection.commit()
        return JSONResponse(
            _serialize_issue(connection, issue_id),
            status_code=201,
            headers={
                **_json_headers(),
                "Cache-Control": "max-age=0, private, must-revalidate",
                "Location": f"http://127.0.0.1:3000/issues/{issue_id}",
            },
        )
    finally:
        connection.close()


@app.put("/issues/{issue_id}.json")
async def update_issue(issue_id: int, request: Request):
    payload = await request.json()
    attributes = payload.get("issue") or {}
    connection = _connect()
    try:
        user = _user(connection, request)
        issue = connection.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if user is None or issue is None:
            return Response(status_code=403, headers={"Cache-Control": "no-cache"})
        permissions = _permissions(connection, user["id"], issue["project_id"])
        if "edit_issues" not in permissions:
            return Response(status_code=403, headers={"Cache-Control": "no-cache"})

        now = _now().strftime("%Y-%m-%d %H:%M:%S")
        old_status = issue["status_id"]
        new_status = attributes.get("status_id", old_status)
        transition = connection.execute(
            "SELECT 1 FROM workflows WHERE tracker_id=? AND old_status_id=? "
            "AND new_status_id=? AND type='WorkflowTransition' AND role_id IN "
            "(SELECT member_roles.role_id FROM members JOIN member_roles "
            "ON member_roles.member_id=members.id WHERE members.user_id=? "
            "AND members.project_id=?) LIMIT 1",
            (issue["tracker_id"], old_status, new_status, user["id"], issue["project_id"]),
        ).fetchone()
        status_changed = new_status != old_status and transition is not None
        if status_changed:
            connection.execute(
                "UPDATE issues SET status_id=?,updated_on=?,lock_version=lock_version+1 WHERE id=?",
                (new_status, now, issue_id),
            )
        else:
            connection.execute(
                "UPDATE issues SET updated_on=?,lock_version=lock_version+1 WHERE id=?",
                (now, issue_id),
            )

        notes = attributes.get("notes")
        if notes is not None or status_changed:
            # LEGACYLIFT_AUDIT_FAULT_HOOK
            cursor = connection.execute(
                "INSERT INTO journals (journalized_id,journalized_type,user_id,notes,created_on,"
                "private_notes) VALUES (?,'Issue',?,?,?,0)",
                (issue_id, user["id"], notes, now),
            )
            if status_changed:
                connection.execute(
                    "INSERT INTO journal_details (journal_id,property,prop_key,old_value,value) "
                    "VALUES (?,'attr','status_id',?,?)",
                    (cursor.lastrowid, str(old_status), str(new_status)),
                )
        connection.commit()
        return Response(status_code=204, headers={"Cache-Control": "no-cache"})
    finally:
        connection.close()
