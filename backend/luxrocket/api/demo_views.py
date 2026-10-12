"""Development-only demo operator page (never routed unless DEBUG and DEMO_PAGES are on).

It plays the operator's role: creates a sandbox session server-side and embeds the game with
the SDK, so the postMessage launch handshake can be exercised end to end.
"""

import html
import json
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse

from luxrocket.gaming import sessions
from luxrocket.operators.models import Operator

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo Operator · LUX ROCKET</title>
<style>
  body {{ margin:0; font-family: system-ui, sans-serif; background:#101318; color:#e6e8ee; }}
  header {{ display:flex; justify-content:space-between; padding:10px 16px; background:#1a1f29; }}
  #game {{ height: calc(100dvh - 44px); }}
</style></head>
<body>
<header><strong>Demo Operator</strong><span>Player: {player}</span></header>
<div id="game"></div>
<script>{sdk}</script>
<script>
  window.__events = [];
  LuxRocket.mount({{
    container: document.getElementById("game"),
    iframeUrl: {iframe_url},
    launchToken: {launch_token},
    onEvent: function (m) {{ window.__events.push(m.type); }}
  }});
</script>
</body></html>"""


def demo_operator(request: HttpRequest) -> HttpResponse:
    if not (settings.DEBUG and settings.DEMO_PAGES):
        raise Http404
    operator = Operator.objects.filter(legal_name="Demo Sandbox Operator").first()
    if operator is None:
        return HttpResponse("Run `manage.py seed_demo` first.", status=503)
    player = request.GET.get("player", "demo-player")[:64]
    created = sessions.create_session(
        operator,
        {
            "player": {"id": player, "country": "ZW", "alias": player[:24]},
            "currency": "USD",
            "game": "lux-rocket",
            "mode": "SANDBOX",
        },
    )
    iframe_url = f"{settings.PLAY_BASE_URL}/launch?op={operator.public_id}&lang=en"
    sdk = (Path(settings.SDK_PATH)).read_text()
    body = PAGE.format(
        player=html.escape(player),
        sdk=sdk,
        iframe_url=json.dumps(iframe_url),
        launch_token=json.dumps(created.launch_token),
    )
    response = HttpResponse(body)
    # The demo page frames the game; it must not itself be framed.
    response["X-Frame-Options"] = "DENY"
    return response
