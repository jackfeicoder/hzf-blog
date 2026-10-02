import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from auth import get_current_user, is_superadmin
from database import get_db
from models import Post, User
from study_models import StudyDay, StudyItem, StudyProgress, StudyRound

router = APIRouter(prefix="/api/study", tags=["study"])
Kind = Literal["java", "hot100", "project"]
LIMITS = {"java": 5, "hot100": 2, "project": 1}
LABELS = {"java": "Java八股", "hot100": "Hot100", "project": "项目学习"}


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


def admin(user=Depends(get_current_user)):
    if not (user.is_admin or is_superadmin(user)):
        raise HTTPException(403, "仅管理员可以维护公共题库")
    return user


class ItemInput(BaseModel):
    kind: Kind
    title: str = Field(min_length=1, max_length=500)
    answer: str = Field(default="", max_length=50000)
    source_url: str = Field(default="", max_length=500)
    position: int = Field(default=0, ge=0, le=1000000)
    active: bool = True

    @field_validator("title")
    @classmethod
    def title_required(cls, value):
        if not value.strip():
            raise ValueError("请输入题目标题")
        return value.strip()

    @field_validator("source_url")
    @classmethod
    def safe_link(cls, value):
        if value and not (value.startswith("/post/") or re.match(r"^https?://[^\s]+$", value)):
            raise ValueError("文章链接须为 /post/编号 或 http(s) 地址")
        return value


def item_json(item):
    return {k: getattr(item, k) for k in ("id", "kind", "title", "answer", "source_url", "position", "active")}


def parse_article(content, kind, post_id):
    """Conservative numbered Markdown parser. Always preview before import."""
    candidates, headings, current, fenced = [], [], None, False
    for line in content.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        heading = re.match(r"^(#{1,6})\s+(.+)", line) if not fenced else None
        question = re.match(r"^\d+[.、)]\s*(\S.*)", line) if not fenced else None
        if heading or question:
            if current:
                current["answer"] = "\n".join(current.pop("lines")).strip()
                candidates.append(current)
                current = None
            if heading:
                level = len(heading[1])
                headings = [(n, text) for n, text in headings if n < level]
                headings.append((level, heading[2].strip()))
            elif len(question[1]) <= 450:
                section = headings[-1][1] if headings else ""
                title = f"{section} · {question[1]}" if section else question[1]
                current = {"kind": kind, "title": title[:500], "lines": [], "source_url": f"/post/{post_id}", "position": len(candidates), "active": True}
        elif current:
            current["lines"].append(line)
    if current:
        current["answer"] = "\n".join(current.pop("lines")).strip()
        candidates.append(current)
    return candidates[:500]


def seed_bank(db):
    # Seed only safe checkboxes. Article parsing is an explicit admin preview step.
    if db.query(StudyItem).filter(StudyItem.kind == "project").first():
        return
    for position, title in enumerate(["HelloAgent", "paicli", "RAG"]):
        db.add(StudyItem(kind="project", title=f"{title}：完成当前阶段学习", answer="默认阶段任务，请管理员拆分为实际章节或里程碑，再按顺序学习。", position=position))
    db.commit()


def current_round(db, user_id, kind):
    row = db.query(StudyRound).filter_by(user_id=user_id, kind=kind).order_by(StudyRound.number.desc()).first()
    if row is None:
        row = StudyRound(user_id=user_id, kind=kind, number=1)
        db.add(row)
        db.flush()
    return row


def members(db, round_id):
    return db.query(StudyProgress, StudyItem).join(StudyItem, StudyProgress.item_id == StudyItem.id).filter(StudyProgress.round_id == round_id).order_by(StudyItem.position, StudyItem.id).all()


def sync_round(db, row):
    if row.finished:
        return
    existing = {p.item_id for p, _ in members(db, row.id)}
    for item in db.query(StudyItem).filter_by(kind=row.kind, active=True).all():
        if item.id not in existing:
            db.add(StudyProgress(round_id=row.id, item_id=item.id))
    db.flush()


def refresh_finished(db, row):
    active = [(p, i) for p, i in members(db, row.id) if i.active and p.included]
    # A frozen daily task still needs completion, even if its item is deactivated.
    day = db.query(StudyDay).filter_by(user_id=row.user_id, date=today()).first()
    outstanding = any(t.get("round_id") == row.id and not t["done"] for t in json.loads(day.tasks_json)) if day else False
    row.finished = bool(active) and all(p.done for p, _ in active) and not outstanding
    if row.finished:
        for progress, item in members(db, row.id):
            if not item.active and not progress.done:
                progress.included = False


def get_day(db, user_id):
    date = today()
    existing = db.query(StudyDay).filter_by(user_id=user_id, date=date).first()
    if existing:
        return existing
    tasks = []
    for kind, limit in LIMITS.items():
        row = current_round(db, user_id, kind)
        sync_round(db, row)
        if not row.finished:
            refresh_finished(db, row)
        pending = [(p, i) for p, i in members(db, row.id) if i.active and p.included and not p.done]
        for progress, item in pending[:limit]:
            tasks.append({"key": f"p-{progress.id}", "kind": kind, "title": item.title, "answer": item.answer, "source_url": item.source_url, "round_id": row.id, "round": row.number, "progress_id": progress.id, "done": False, "weak": progress.weak, "note": ""})
        if not db.query(StudyItem).filter_by(kind=kind, active=True).first():
            post = db.query(Post).filter_by(title="Java八股", published=True).first() if kind == "java" else None
            for n in range(limit):
                tasks.append({"key": f"fallback-{kind}-{n}", "kind": kind, "title": f"{LABELS[kind]} · 今日第 {n + 1} 项", "answer": "题库待维护：请从文章自行选择学习内容，完成后勾选。导入题库后将按具体题目记录轮次。", "source_url": f"/post/{post.id}" if post else ("/post/5" if kind == "hot100" else ""), "done": False, "weak": False, "note": ""})
    day = StudyDay(user_id=user_id, date=date, tasks_json=json.dumps(tasks, ensure_ascii=False))
    db.add(day)
    db.commit()
    return day


def day_json(day):
    tasks = json.loads(day.tasks_json)
    return {"date": day.date, "tasks": tasks, "done": sum(t["done"] for t in tasks), "total": len(tasks)}


@router.get("/today")
def read_today(response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    private_response(response)
    try:
        return day_json(get_day(db, user.id))
    except IntegrityError:
        db.rollback()
        existing = db.query(StudyDay).filter_by(user_id=user.id, date=today()).first()
        if existing:
            return day_json(existing)
        return day_json(get_day(db, user.id))


class TaskUpdate(BaseModel):
    done: bool
    weak: bool = False
    note: str = Field(default="", max_length=2000)


@router.put("/today/tasks/{key}")
def update_task(key: str, body: TaskUpdate, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    private_response(response)
    day = db.query(StudyDay).filter_by(user_id=user.id, date=today()).with_for_update().first()
    previous_json = day.tasks_json if day else ""
    tasks = json.loads(day.tasks_json) if day else []
    task = next((t for t in tasks if t["key"] == key), None)
    if task is None:
        raise HTTPException(404, "今日任务不存在，请刷新页面")
    task.update(body.model_dump())
    if task.get("progress_id"):
        row = db.query(StudyRound).filter_by(id=task["round_id"], user_id=user.id).first()
        latest = current_round(db, user.id, task["kind"])
        if row.id != latest.id:
            raise HTTPException(409, "已开始下一轮，上一轮记录已归档")
        progress = db.query(StudyProgress).filter_by(id=task["progress_id"], round_id=row.id).first()
        progress.done, progress.weak = body.done, body.weak
    new_json = json.dumps(tasks, ensure_ascii=False)
    # SQLite ignores FOR UPDATE: use compare-and-swap to avoid lost checkmarks
    # when two browser tabs update different tasks at the same time.
    updated = db.query(StudyDay).filter_by(id=day.id, tasks_json=previous_json).update({"tasks_json": new_json}, synchronize_session=False)
    if not updated:
        db.rollback()
        raise HTTPException(409, "其他页面已更新打卡，请刷新后重试")
    set_committed_value(day, "tasks_json", new_json)
    db.flush()
    if task.get("progress_id"):
        refresh_finished(db, row)
    db.commit()
    return day_json(day)


@router.get("/progress")
def read_progress(response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    private_response(response)
    result = []
    for row in db.query(StudyRound).filter_by(user_id=user.id).order_by(StudyRound.kind, StudyRound.number.desc()).all():
        items = members(db, row.id)
        included = [(p, i) for p, i in items if p.included and (row.finished or i.active)]
        result.append({"id": row.id, "kind": row.kind, "number": row.number, "finished": row.finished, "done": sum(p.done for p, _ in included), "total": len(included), "weak": sum(p.weak for p, _ in included)})
    return result


class NextRound(BaseModel):
    mode: Literal["all", "weak"] = "all"


@router.post("/rounds/{kind}/next")
def next_round(kind: Kind, body: NextRound, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = current_round(db, user.id, kind)
    if not row.finished:
        raise HTTPException(409, "请先完成当前轮次")
    active = db.query(StudyItem).filter_by(kind=kind, active=True).order_by(StudyItem.position, StudyItem.id).all()
    if body.mode == "weak":
        weak_ids = {p.item_id for p, _ in members(db, row.id) if p.weak}
        active = [i for i in active if i.id in weak_ids]
    if not active:
        raise HTTPException(400, "没有可复习题目")
    new = StudyRound(user_id=user.id, kind=kind, number=row.number + 1)
    db.add(new)
    try:
        db.flush()
        for item in active:
            db.add(StudyProgress(round_id=new.id, item_id=item.id))
        # Excluded items are not falsely counted as completed review work.
        if body.mode == "weak":
            selected = {i.id for i in active}
            for item in db.query(StudyItem).filter_by(kind=kind, active=True).all():
                if item.id not in selected:
                    db.add(StudyProgress(round_id=new.id, item_id=item.id, included=False))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "轮次已更新，请刷新")
    return {"number": new.number, "message": "新轮次从次日任务开始，当天任务保留"}


@router.get("/history")
def history(response: Response, month: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    private_response(response)
    month = month or today()[:7]
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(400, "月份格式为 YYYY-MM")
    return [day_json(d) for d in db.query(StudyDay).filter(StudyDay.user_id == user.id, StudyDay.date.like(month + "-%")).order_by(StudyDay.date.desc()).all()]


@router.get("/bank")
def bank(response: Response, db: Session = Depends(get_db), user=Depends(admin)):
    private_response(response)
    return [item_json(i) for i in db.query(StudyItem).order_by(StudyItem.kind, StudyItem.position, StudyItem.id).all()]


@router.post("/bank")
def add_item(body: ItemInput, db: Session = Depends(get_db), user=Depends(admin)):
    item = StudyItem(**body.model_dump())
    db.add(item)
    db.commit()
    return item_json(item)


@router.put("/bank/{item_id}")
def edit_item(item_id: int, body: ItemInput, db: Session = Depends(get_db), user=Depends(admin)):
    item = db.get(StudyItem, item_id)
    if not item:
        raise HTTPException(404, "题目不存在")
    if item.kind != body.kind:
        raise HTTPException(400, "已有题目的分类固定，请新建另一分类的题目")
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    db.commit()
    return item_json(item)


class PreviewInput(BaseModel):
    post_id: int = Field(gt=0)
    kind: Literal["java", "hot100"]


@router.post("/bank/preview")
def preview(body: PreviewInput, db: Session = Depends(get_db), user=Depends(admin)):
    post = db.get(Post, body.post_id)
    if not post:
        raise HTTPException(404, "文章不存在")
    return {"title": post.title, "items": parse_article(post.content, body.kind, post.id)}


class ImportInput(BaseModel):
    items: list[ItemInput] = Field(min_length=1, max_length=500)


@router.post("/bank/import")
def import_items(body: ImportInput, db: Session = Depends(get_db), user=Depends(admin)):
    existing = {(i.kind, i.title, i.source_url) for i in db.query(StudyItem).all()}
    count = 0
    for item in body.items:
        key = (item.kind, item.title, item.source_url)
        if key not in existing:
            db.add(StudyItem(**item.model_dump()))
            existing.add(key)
            count += 1
    db.commit()
    return {"added": count, "skipped": len(body.items) - count}
