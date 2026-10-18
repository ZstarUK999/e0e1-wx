import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from app.db.models import Base, Player, HandshakeLog
from app.domain import auth
from app.http.routers.logs import list_logs


def test_binding_remarks_follow_package_instead_of_login_and_support_legacy():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Player(player_id="owner", nickname="发包对象"), Player(player_id="member", nickname="同包成员"), Player(player_id="outsider", nickname="外来登录者")])
        auth.record(session, verdict=auth.Verdict.denied(auth.REASON_ID_MISMATCH), bound_player_id="owner", bound_player_ids=["owner", "member"], login_player_id="outsider", guild="", client_version="", remote="")
        session.add(HandshakeLog(bound_player_id="owner"))
        session.add(HandshakeLog(bound_player_id="deleted", bound_player_ids="invalid-json"))
        session.commit()
        queries=[]
        def count(*args): queries.append(args[2])
        event.listen(engine, "before_cursor_execute", count)
        rows=list_logs(limit=200, session=session, _admin="admin")
        event.remove(engine, "before_cursor_execute", count)
        assert len(queries)==2  # 日志与全部玩家备注各一次，避免 N+1 查询
        assert rows[0].bound_players[0].nickname == ""
        assert rows[1].bound_player_nickname == "发包对象"
        assert rows[2].player_id == "outsider"
        assert rows[2].bound_player_nickname == "发包对象"
        assert [(p.player_id,p.nickname) for p in rows[2].bound_players] == [("owner","发包对象"),("member","同包成员")]
        session.query(Player).filter_by(player_id="owner").one().nickname="更新备注"
        session.commit()
        assert list_logs(session=session, _admin="admin")[2].bound_player_nickname == "更新备注"
