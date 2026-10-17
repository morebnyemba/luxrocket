defmodule LuxRtWeb.GameChannel do
  @moduledoc """
  Protocol `lr.v1` (doc 10). Commands are validated and stamped with the server receipt time
  here, then forwarded to the stream's coordinator. A reply only means "received"; results
  arrive as separate private events.
  """
  use Phoenix.Channel
  require Logger

  alias LuxRt.Rounds.{Coordinator, Snapshot}

  @max_commands_per_second 10

  @impl true
  def join("stream:" <> stream, %{"protocol" => "lr.v1"}, socket) do
    session = socket.assigns.session

    if session["stream_id"] == stream do
      Phoenix.PubSub.subscribe(LuxRt.PubSub, "session:" <> session["session_id"])

      socket =
        socket |> assign(:stream, stream) |> assign(:pseq, 0) |> assign(:window, {now_s(), 0})

      {:ok,
       %{type: "SESSION_READY", v: 1, server_ts: now(), data: ready_payload(stream, session)},
       socket}
    else
      {:error, %{code: "ROUND_MISMATCH"}}
    end
  end

  def join(_topic, _params, _socket), do: {:error, %{code: "PROTOCOL_ERROR"}}

  @impl true
  def handle_in("cmd", payload, socket) do
    received_at = now()

    with {:ok, socket} <- rate_limit(socket),
         {:ok, cmd} <- parse(payload) do
      dispatch(cmd, received_at, socket)
      {:reply, {:ok, %{command_id: cmd["command_id"], received_at: received_at}}, socket}
    else
      {:error, code, socket} -> {:reply, {:error, %{code: code}}, socket}
      {:error, code} -> {:reply, {:error, %{code: code}}, socket}
    end
  end

  def handle_in(_event, _payload, socket),
    do: {:reply, {:error, %{code: "PROTOCOL_ERROR"}}, socket}

  @impl true
  def handle_info({:lr_private, type, data}, socket) do
    pseq = socket.assigns.pseq + 1
    push(socket, type, %{type: type, v: 1, pseq: pseq, server_ts: now(), data: data})

    if type == "SESSION_REVOKED" do
      {:stop, :normal, assign(socket, :pseq, pseq)}
    else
      {:noreply, assign(socket, :pseq, pseq)}
    end
  end

  def handle_info(_msg, socket), do: {:noreply, socket}

  # ---- commands ----------------------------------------------------------------------------

  defp dispatch(%{"type" => "PLACE_BET"} = cmd, received_at, socket) do
    d = cmd["data"]

    Coordinator.place_bet(socket.assigns.stream, %{
      session_id: socket.assigns.session["session_id"],
      command_id: cmd["command_id"],
      round_id: cmd["round_id"],
      panel: d["panel"],
      stake: d["stake"],
      auto: d["auto_cashout_x10000"],
      received_at: received_at
    })
  end

  defp dispatch(%{"type" => "CASH_OUT"} = cmd, received_at, socket) do
    Coordinator.cash_out(socket.assigns.stream, %{
      session_id: socket.assigns.session["session_id"],
      command_id: cmd["command_id"],
      bet_id: cmd["data"]["bet_id"],
      received_at: received_at
    })
  end

  defp dispatch(%{"type" => "SYNC"}, _received_at, socket) do
    stream = socket.assigns.stream

    send(
      self(),
      {:lr_private, "ROUND_SNAPSHOT", snapshot(stream, socket.assigns.session["session_id"])}
    )
  end

  defp dispatch(%{"type" => "TIME_PING"} = cmd, received_at, _socket) do
    send(
      self(),
      {:lr_private, "TIME_PONG", %{client_ts: cmd["data"]["client_ts"], server_ts: received_at}}
    )
  end

  # Syntax validation only; business rules belong to the coordinator and Django.
  defp parse(%{"type" => type, "v" => 1, "command_id" => id} = cmd) when is_binary(id) do
    with {:ok, _} <- Ecto.UUID.cast(id),
         :ok <- validate(type, cmd) do
      {:ok, cmd}
    else
      _ -> {:error, "PROTOCOL_ERROR"}
    end
  end

  defp parse(_), do: {:error, "PROTOCOL_ERROR"}

  defp validate("PLACE_BET", %{"round_id" => r, "data" => %{"panel" => p, "stake" => s} = d})
       when is_binary(r) and is_integer(p) and p in 0..7 and is_binary(s) do
    auto = d["auto_cashout_x10000"]

    cond do
      not Regex.match?(~r/^[1-9][0-9]{0,17}$/, s) -> :error
      auto != nil and not (is_integer(auto) and auto >= 10_100 and rem(auto, 100) == 0) -> :error
      true -> :ok
    end
  end

  defp validate("CASH_OUT", %{"round_id" => r, "data" => %{"bet_id" => b}})
       when is_binary(r) and is_binary(b),
       do: :ok

  defp validate("SYNC", _), do: :ok
  defp validate("TIME_PING", %{"data" => %{"client_ts" => ts}}) when is_integer(ts), do: :ok
  defp validate(_, _), do: :error

  defp rate_limit(socket) do
    {second, count} = socket.assigns.window
    current = now_s()

    cond do
      current != second -> {:ok, assign(socket, :window, {current, 1})}
      count < @max_commands_per_second -> {:ok, assign(socket, :window, {second, count + 1})}
      true -> {:error, "RATE_LIMITED", socket}
    end
  end

  # ---- snapshots ---------------------------------------------------------------------------

  defp ready_payload(stream, session) do
    %{session: session, snapshot: snapshot(stream, session["session_id"])}
  end

  defp snapshot(stream, session_id) do
    base =
      Snapshot.get(stream) ||
        %{stream_id: stream, seq: 0, server_ts: now(), round: nil, recent_crashes: []}

    Map.put(base, :player_bets, Coordinator.player_view(stream, session_id))
  end

  defp now, do: System.os_time(:millisecond)
  defp now_s, do: System.os_time(:second)
end
