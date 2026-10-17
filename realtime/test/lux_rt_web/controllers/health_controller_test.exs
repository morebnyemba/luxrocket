defmodule LuxRtWeb.HealthControllerTest do
  use LuxRtWeb.ConnCase, async: true

  test "GET /healthz reports database reachability", %{conn: conn} do
    assert %{"status" => "ok", "db" => true} = conn |> get(~p"/healthz") |> json_response(200)
  end
end
