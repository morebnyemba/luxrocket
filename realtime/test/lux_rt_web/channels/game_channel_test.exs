defmodule LuxRtWeb.GameChannelTest do
  use LuxRtWeb.ChannelCase, async: false

  alias LuxRt.PlatformStub
  alias LuxRtWeb.{GameChannel, UserSocket}

  setup do
    Ecto.Adapters.SQL.Sandbox.mode(LuxRt.Repo, {:shared, self()})
    start_supervised!(PlatformStub)
    :ok
  end

  test "connect requires a valid single-use ticket" do
    assert {:ok, socket} = connect(UserSocket, %{"ticket" => "good-ticket"})
    assert socket.assigns.session["session_id"] == "ses_test"
    assert :error = connect(UserSocket, %{"ticket" => "bad"})
    assert :error = connect(UserSocket, %{})
  end

  test "join returns SESSION_READY with a snapshot; foreign streams are refused" do
    {:ok, socket} = connect(UserSocket, %{"ticket" => "good-ticket"})

    assert {:ok, reply, _socket} =
             subscribe_and_join(socket, GameChannel, "stream:global", %{"protocol" => "lr.v1"})

    assert reply.type == "SESSION_READY"
    assert reply.data.snapshot.stream_id == "global"

    assert {:error, %{code: "ROUND_MISMATCH"}} =
             subscribe_and_join(socket, GameChannel, "stream:other", %{"protocol" => "lr.v1"})
  end

  test "commands are validated, stamped and acknowledged as received" do
    {:ok, socket} = connect(UserSocket, %{"ticket" => "good-ticket"})

    {:ok, _, socket} =
      subscribe_and_join(socket, GameChannel, "stream:global", %{"protocol" => "lr.v1"})

    ref = push(socket, "cmd", %{"type" => "PLACE_BET", "v" => 1, "command_id" => "not-a-uuid"})
    assert_reply ref, :error, %{code: "PROTOCOL_ERROR"}

    bad_target = %{
      "type" => "PLACE_BET",
      "v" => 1,
      "command_id" => Ecto.UUID.generate(),
      "round_id" => "r",
      "data" => %{"panel" => 0, "stake" => "500", "auto_cashout_x10000" => 15_050}
    }

    assert_reply push(socket, "cmd", bad_target), :error, %{code: "PROTOCOL_ERROR"}

    id = Ecto.UUID.generate()
    ping = %{"type" => "TIME_PING", "v" => 1, "command_id" => id, "data" => %{"client_ts" => 123}}
    ref = push(socket, "cmd", ping)
    assert_reply ref, :ok, %{command_id: ^id, received_at: _}
    assert_push "TIME_PONG", %{data: %{client_ts: 123}}

    sync = %{"type" => "SYNC", "v" => 1, "command_id" => Ecto.UUID.generate()}
    assert_reply push(socket, "cmd", sync), :ok, _
    assert_push "ROUND_SNAPSHOT", %{data: %{stream_id: "global"}}
  end

  test "per-socket command rate limit" do
    {:ok, socket} = connect(UserSocket, %{"ticket" => "good-ticket"})

    {:ok, _, socket} =
      subscribe_and_join(socket, GameChannel, "stream:global", %{"protocol" => "lr.v1"})

    refs =
      for _ <- 1..15 do
        push(socket, "cmd", %{"type" => "SYNC", "v" => 1, "command_id" => Ecto.UUID.generate()})
      end

    replies =
      for ref <- refs,
          do:
            (receive do
               %Phoenix.Socket.Reply{ref: ^ref, status: s} -> s
             after
               1_000 -> :timeout
             end)

    assert Enum.count(replies, &(&1 == :error)) >= 1
  end

  test "private events are pushed with a per-session sequence" do
    {:ok, socket} = connect(UserSocket, %{"ticket" => "good-ticket"})

    {:ok, _, _socket} =
      subscribe_and_join(socket, GameChannel, "stream:global", %{"protocol" => "lr.v1"})

    Phoenix.PubSub.broadcast(
      LuxRt.PubSub,
      "session:ses_test",
      {:lr_private, "SETTLEMENT_CONFIRMED", %{bet_id: "b"}}
    )

    assert_push "SETTLEMENT_CONFIRMED", %{pseq: 1, data: %{bet_id: "b"}}
  end
end
