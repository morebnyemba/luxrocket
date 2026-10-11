defmodule LuxRtWeb.InternalControllerTest do
  use LuxRtWeb.ConnCase, async: false

  @token "Bearer dev-internal-token"

  defp post_events(conn, events, auth \\ @token) do
    conn
    |> put_req_header("authorization", auth)
    |> post(~p"/internal/v1/platform-events", %{events: events})
  end

  test "requires the service token", %{conn: conn} do
    assert conn |> post_events([], "Bearer nope") |> json_response(401)
  end

  test "delivers settlement confirmations once per event id", %{conn: conn} do
    Phoenix.PubSub.subscribe(LuxRt.PubSub, "session:ses_x")

    event = %{
      "event_id" => Ecto.UUID.generate(),
      "type" => "settlement.confirmed",
      "payload" => %{
        "session_id" => "ses_x",
        "bet_id" => "bet_1",
        "kind" => "CREDIT",
        "amount" => "750"
      }
    }

    assert %{"accepted" => 1} = conn |> post_events([event]) |> json_response(200)

    assert_receive {:lr_private, "SETTLEMENT_CONFIRMED",
                    %{"bet_id" => "bet_1", "amount" => "750"}}

    build_conn() |> post_events([event]) |> json_response(200)
    refute_receive {:lr_private, "SETTLEMENT_CONFIRMED", _}, 100
  end

  test "session revocation is pushed to the session", %{conn: conn} do
    Phoenix.PubSub.subscribe(LuxRt.PubSub, "session:ses_y")

    event = %{
      "event_id" => Ecto.UUID.generate(),
      "type" => "session.revoked",
      "payload" => %{"session_id" => "ses_y", "reason" => "OPERATOR_REVOKED"}
    }

    conn |> post_events([event]) |> json_response(200)
    assert_receive {:lr_private, "SESSION_REVOKED", %{reason: "OPERATOR_REVOKED"}}
  end
end
