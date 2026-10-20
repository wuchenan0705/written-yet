"""Password-protected web dashboard."""
import hmac
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app import clock, config, images, push, submissions, writing_guide
from app.db import get_session
from app.grader import ERROR_TYPES, GradingError
from app.logic import (
    get_or_create_day,
    get_settings,
    leaves_used,
    outstanding_fines,
    update_settings,
)
from app.models import SKILL_ZH, SKILLS, FineEntry, Mistake, Submission, SubmissionImage

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals.update(SKILL_ZH=SKILL_ZH, SKILLS=SKILLS)


class LoginRequired(Exception):
    pass


def require_login(request: Request) -> None:
    if not request.session.get("auth"):
        raise LoginRequired()


Auth = Depends(require_login)


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, ctx)


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", error=None)


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    if config.WEB_PASSWORD and hmac.compare_digest(password, config.WEB_PASSWORD):
        request.session["auth"] = True
        return RedirectResponse("/", 303)
    return render(request, "login.html", error="密碼錯誤")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


@router.get("/", dependencies=[Auth])
def dashboard(request: Request, session: Session = Depends(get_session)):
    now = clock.now()
    st = get_settings(session)
    day = get_or_create_day(session, st, now.date().isoformat())
    recent = session.exec(select(Submission).order_by(Submission.id.desc()).limit(10)).all()
    return render(
        request, "dashboard.html", st=st, day=day, recent=recent,
        leaves_left=st.leave_per_month - leaves_used(session, day.date),
        fines=outstanding_fines(session),
        push_left=push.remaining(session, st, now),
    )


@router.get("/submit", dependencies=[Auth])
def submit_page(request: Request, skill: str = "reading"):
    return render(request, "submit.html", skill=skill, text="", error=None)


@router.post("/submit", dependencies=[Auth])
async def submit(request: Request, skill: str = Form(...), text: str = Form(""),
                 book: str = Form(""), test: str = Form(""), part: str = Form(""),
                 files: list[UploadFile] = File(default=[]),
                 session: Session = Depends(get_session)):
    files = [f for f in files if f.filename]
    if skill not in SKILLS or not (text.strip() or files):
        return render(request, "submit.html", skill=skill, text=text, error="請選科目，並貼上文字或截圖")
    if len(files) > images.MAX_IMAGES:
        return render(request, "submit.html", skill=skill, text=text,
                      error=f"一次最多 {images.MAX_IMAGES} 張截圖")
    try:
        imgs = [images.normalize(await f.read()) for f in files]
        sub, finished = await run_in_threadpool(
            submissions.process, session, skill, text.strip(), "web", clock.now(), imgs,
            book_info={"book": book, "test": test, "part": part},
        )
    except (GradingError, images.ImageError) as e:
        return render(request, "submit.html", skill=skill, text=text, error=str(e))
    return RedirectResponse(f"/submissions/{sub.id}?finished={int(finished)}", 303)


@router.get("/submissions/{sub_id}", dependencies=[Auth])
def submission_detail(request: Request, sub_id: int, finished: int = 0,
                      session: Session = Depends(get_session)):
    sub = session.get(Submission, sub_id)
    if not sub:
        raise HTTPException(404)
    mistakes = session.exec(select(Mistake).where(Mistake.submission_id == sub_id)).all()
    image_ids = session.exec(
        select(SubmissionImage.id).where(SubmissionImage.submission_id == sub_id)
    ).all()
    return render(request, "submission.html", sub=sub, r=sub.result, mistakes=mistakes,
                  finished=bool(finished), image_ids=image_ids)


@router.get("/images/{image_id}", dependencies=[Auth])
def submission_image(image_id: int, session: Session = Depends(get_session)):
    img = session.get(SubmissionImage, image_id)
    if not img:
        raise HTTPException(404)
    return Response(img.data, media_type=img.media_type)


@router.get("/mistakes", dependencies=[Auth])
def mistakes_page(request: Request, skill: str = "", book: str = "", test: str = "",
                  part: str = "", error_type: str = "", show: str = "open",
                  session: Session = Depends(get_session)):
    q = (select(Mistake, Submission)
         .join(Submission, Mistake.submission_id == Submission.id)
         .order_by(Submission.id.desc(), Mistake.id))
    filters = {Mistake.skill: skill, Submission.book: book, Submission.test: test,
               Submission.part: part, Mistake.error_type: error_type}
    for col, val in filters.items():
        if val:
            q = q.where(col == val)
    if show == "open":
        q = q.where(Mistake.understood == False)  # noqa: E712
    rows = session.exec(q.limit(500)).all()

    # One card per passage/section so mistakes from different sets don't blur together.
    groups: dict[int, dict] = {}
    for m, sub in rows:
        g = groups.setdefault(sub.id, {"sub": sub, "items": []})
        g["items"].append(m)

    open_rows = session.exec(
        select(Mistake, Submission).join(Submission, Mistake.submission_id == Submission.id)
        .where(Mistake.understood == False)  # noqa: E712
    ).all()
    stats = Counter(m.error_type for m, _ in open_rows).most_common()
    book_stats = Counter(sub.book or "未分類" for _, sub in open_rows).most_common()

    def options(col, **where):
        sq = select(col).distinct().where(col != "")
        for c, v in where.items():
            if v:
                sq = sq.where(getattr(Submission, c) == v)
        return sorted(session.exec(sq).all())

    return render(
        request, "mistakes.html", groups=list(groups.values()), stats=stats, book_stats=book_stats,
        skill=skill, book=book, test=test, part=part, error_type=error_type, show=show,
        error_types=ERROR_TYPES, books=options(Submission.book),
        tests=options(Submission.test, book=book),
        parts=options(Submission.part, book=book, test=test),
    )


@router.post("/mistakes/{mid}/toggle", dependencies=[Auth])
def toggle_mistake(request: Request, mid: int, session: Session = Depends(get_session)):
    m = session.get(Mistake, mid)
    if m:
        m.understood = not m.understood
        session.add(m)
        session.commit()
    return RedirectResponse(request.headers.get("referer") or "/mistakes", 303)


@router.get("/writing", dependencies=[Auth])
def writing_guide_page(request: Request):
    return render(request, "writing.html", g=writing_guide)


@router.get("/settings", dependencies=[Auth])
def settings_page(request: Request, session: Session = Depends(get_session)):
    return render(request, "settings.html", st=get_settings(session), notes=[])


@router.post("/settings", dependencies=[Auth])
async def save_settings(request: Request, session: Session = Depends(get_session)):
    form = dict(await request.form())
    st = get_settings(session)
    try:
        notes = update_settings(session, st, form, clock.now())
    except ValueError:
        session.rollback()
        notes = ["格式錯誤，請檢查數字與時間（HH:MM）。"]
    session.refresh(st)
    return render(request, "settings.html", st=st, notes=notes or ["已儲存 ✅"])


@router.get("/fines", dependencies=[Auth])
def fines_page(request: Request, session: Session = Depends(get_session)):
    items = session.exec(select(FineEntry).order_by(FineEntry.id.desc())).all()
    return render(request, "fines.html", items=items, total=outstanding_fines(session),
                  st=get_settings(session))


@router.post("/fines/{fid}/paid", dependencies=[Auth])
def mark_paid(fid: int, session: Session = Depends(get_session)):
    f = session.get(FineEntry, fid)
    if f and not f.paid:
        f.paid = True
        f.paid_at = clock.now()
        session.add(f)
        session.commit()
    return RedirectResponse("/fines", 303)
