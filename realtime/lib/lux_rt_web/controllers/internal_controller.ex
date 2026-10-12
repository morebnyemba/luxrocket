defmodule LuxRtWeb.InternalController do
  @moduledoc """
  Platform -> real-time events relayed from Django's outbox (doc 02 §4 channel ③): settlement
  confirmations, session revocations, stream ruleset bindings and seed-chain activations.
  At-least-once; de-duplicated by event id (activation is idempotent in the database instead,
  so a node-local de-dup cache can never swallow it).
  """
  use LuxRtWeb, :controller

  def platform_events(conn, %{"events" => events}) when is_list(events) do
    with :ok <- authorize(conn) do
      Enum.each(events, &handle/1)
      json(conn, %{accepted: length(events)})
    else
      :error -> conn |> put_status(401) |> json(%{code: "UNAUTHORIZED"})
    end
  end

  def platform_events(conn, _params),
    do: conn |> put_status(400) |> json(%{code: "INVALID_REQUEST"})

  defp authorize(conn) do
    expected = "Bearer " <> Application.fetch_env!(:lux_rt, :platform)[:service_token]

    case get_req_header(conn, "authorization") do
      [value] -> if Plug.Crypto.secure_compare(value, expected), do: :ok, else: :error
      _ -> :error
    end
  end

  defp handle(%{"type" => "seed_chain.activate", "payload" => p}) do
    # Written to rt.seed_chain; the coordinator (on whichever node) adopts it at its next round.
    LuxRt.Fairness.SeedChain.activate(p)
  end

  defp handle(%{"event_id" => id} = event) do
    if LuxRt.Tables.first_time?(id), do: deliver(event)
  end

  defp handle(_), do: :ok

  defp deliver(%{"type" => "settlement.confirmed", "payload" => p}) do
    data = Map.take(p, ["bet_id", "panel", "kind", "amount", "balance"])
    private(p["session_id"], "SETTLEMENT_CONFIRMED", data)
  end

  defp deliver(%{"type" => "session.revoked", "payload" => p}) do
    private(p["session_id"], "SESSION_REVOKED", %{reason: p["reason"]})
    LuxRtWeb.Endpoint.broadcast("session:" <> p["session_id"], "disconnect", %{})
  end

  # A newly approved ruleset binding: the coordinator adopts it at the next round boundary.
  defp deliver(%{"type" => "stream.config", "payload" => p}) do
    LuxRt.Rounds.Coordinator.set_rules(p["stream"], p)
  end

  defp deliver(_), do: :ok

  defp private(nil, _type, _data), do: :ok

  defp private(session_id, type, data) do
    Phoenix.PubSub.broadcast(LuxRt.PubSub, "session:" <> session_id, {:lr_private, type, data})
  end
end
