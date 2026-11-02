"""
/api/world — 화면이 읽는 한 덩이.

Supabase 를 **여기서만** 읽는다. 브라우저에는 키를 두지 않는다.
읽기만 하므로 anon 키로 충분하다.
"""
import json
import os

from http.server import BaseHTTPRequestHandler


def _world():
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"],
                       os.environ["SUPABASE_ANON_KEY"])

    out = {}
    # 지도와 지금
    try:
        import atlas
        out["view"] = atlas.view(sb)
        out["replay"] = atlas.replay(sb, hours=24)
    except Exception as e:
        out["error"] = str(e)[:120]
        out["view"] = {"size": [21, 15], "spots": {}, "who": {}}
        out["replay"] = {"frames": []}

    # 몰랑이네 안 — 누르면 펼쳐지는 집
    try:
        import home as HM
        h = HM.load(sb)
        lay = HM.layout()
        out["view"]["home"] = {
            "coords": lay.get("coords") or {},
            "objects": h.get("objects") or {},
            "where": h.get("where") or {},
        }
    except Exception:
        pass
    return out


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = json.dumps(_world(), ensure_ascii=False)
            code = 200
        except Exception as e:
            body = json.dumps({"error": str(e)[:200]}, ensure_ascii=False)
            code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
