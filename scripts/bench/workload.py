import asyncio, time, json, datetime, uuid
import jwt
from fastapi import FastAPI, Depends, Header
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer, DateTime, select, func
from sqlalchemy.orm import declarative_base, Session
import phonenumbers

SECRET = "x" * 40
Base = declarative_base()
class Call(Base):
    __tablename__ = "calls"
    id = Column(String, primary_key=True)
    business_id = Column(String, index=True)
    caller = Column(String)
    summary = Column(String)
    duration = Column(Integer)
    started_at = Column(DateTime)

from sqlalchemy.pool import StaticPool
engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
with Session(engine) as s:
    for i in range(200):
        s.add(Call(id=str(uuid.uuid4()), business_id="b1", caller="+17135550142",
                   summary="Caller reported AC not cooling; lead captured and callback requested " * 2,
                   duration=200 + i, started_at=datetime.datetime(2026, 11, 1) + datetime.timedelta(hours=i)))
    s.commit()

class CallOut(BaseModel):
    id: str
    caller: str
    summary: str
    duration: int
    started_at: datetime.datetime

class Page(BaseModel):
    items: list[CallOut]
    total: int
    minutes: int

app = FastAPI()

async def user(authorization: str = Header()):
    claims = jwt.decode(authorization.split()[1], SECRET, algorithms=["HS256"], audience="authenticated")
    return claims["sub"]

@app.get("/api/calls", response_model=Page)
async def calls(sub: str = Depends(user)):
    with Session(engine) as s:
        rows = s.execute(select(Call).where(Call.business_id == "b1").order_by(Call.started_at.desc()).limit(50)).scalars().all()
        total = s.execute(select(func.count()).select_from(Call).where(Call.business_id == "b1")).scalar()
        minutes = s.execute(select(func.sum(Call.duration)).where(Call.business_id == "b1")).scalar() // 60
        items = [CallOut(id=r.id, caller=phonenumbers.format_number(phonenumbers.parse(r.caller, "US"), phonenumbers.PhoneNumberFormat.NATIONAL),
                         summary=r.summary, duration=r.duration, started_at=r.started_at) for r in rows]
    return Page(items=items, total=total, minutes=minutes)

@app.get("/health")
async def health():
    return {"ok": True}

TOKEN = jwt.encode({"sub": "u1", "aud": "authenticated", "exp": 4102444800}, SECRET, algorithm="HS256")

async def call_asgi(path):
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "https",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": [(b"authorization", f"Bearer {TOKEN}".encode()), (b"host", b"x")],
             "client": ("1.2.3.4", 1), "server": ("x", 443)}
    body = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(msg):
        if msg["type"] == "http.response.body":
            body.append(msg.get("body", b""))
    await app(scope, receive, send)
    return b"".join(body)

async def bench(path, n=40):
    for _ in range(5):
        await call_asgi(path)
    out = []
    for _ in range(n):
        t = time.perf_counter()
        await call_asgi(path)
        out.append((time.perf_counter() - t) * 1000)
    out.sort()
    return round(out[n // 2], 2)

async def main():
    return json.dumps({"health": await bench("/health"), "calls50": await bench("/api/calls")})
