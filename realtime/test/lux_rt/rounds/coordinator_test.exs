defmodule LuxRt.Rounds.CoordinatorTest do
  use LuxRt.DataCase, async: false

  alias LuxRt.Math.{Curve, Outcome}
  alias LuxRt.PlatformStub
  alias LuxRt.Rounds.{Coordinator, Lease}
  alias Phoenix.Socket.Broadcast

  @timing [
    betting_window_ms: 300,
    close_grace_ms: 150,
    crash_grace_ms: 20,
    cooldown_ms: 150,
    tick_ms: 50,
    journal_flush_ms: 2,
    lease_ttl_ms: 2_000,
    lease_renew_ms: 500
  ]

  setup do
    Ecto.Adapters.SQL.Sandbox.mode(LuxRt.Repo, {:shared, self()})
    previous = Application.get_env(:lux_rt, :timing)
    Application.put_env(:lux_rt, :timing, @timing)
    on_exit(fn -> Application.put_env(:lux_rt, :timing, previous) end)
    start_supervised!(PlatformStub)
    stream = "t#{System.unique_integer([:positive])}"
    LuxRtWeb.Endpoint.subscribe("stream:" <> stream)
    {:ok, stream: stream}
  end

  defp start(stream), do: start_supervised!({Coordinator, stream}, restart: :temporary)
  defp state(stream), do: :sys.get_state(Coordinator.via(stream))

  defp await(event, timeout \\ 3_000) do
    assert_receive %Broadcast{event: ^event, payload: payload}, timeout
    payload
  end

  defp private(session), do: Phoenix.PubSub.subscribe(LuxRt.PubSub, "session:" <> session)

  defp bet_cmd(session, round_id, panel, extra \\ %{}) do
    Map.merge(
      %{
        session_id: session,
        command_id: Ecto.UUID.generate(),
        round_id: round_id,
        panel: panel,
        stake: "500",
        auto: nil,
        received_at: System.os_time(:millisecond)
      },
      extra
    )
  end

  # The SQL sandbox runs the whole test in one transaction, so now() is frozen: move the
  # expiry into the past explicitly.
  defp expire_lease(stream) do
    LuxRt.Repo.query!(
      "UPDATE rt.stream_lease SET expires_at = now() - interval '1 minute' WHERE stream_id = $1",
      [stream]
    )
  end

  defp journal(stream) do
    %{rows: rows} =
      LuxRt.Repo.query!(
        "SELECT stream_seq, type, payload FROM rt.round_journal WHERE stream_id = $1 ORDER BY stream_seq",
        [stream]
      )

    rows
  end

  test "a full round is committed, journaled in order and verifiable", %{stream: stream} do
    start(stream)
    open = await("ROUND_OPEN")
    commitment = open.data.commitment

    flying = await("ROCKET_LAUNCHED")

    %{rows: [[nil, nil]]} =
      LuxRt.Repo.query!(
        "SELECT crash_x10000, seed_hex FROM rt.round WHERE round_id = $1::text::uuid",
        [flying.round_id]
      )

    crashed = await("ROUND_CRASHED", 6_000)
    seed = Base.decode16!(crashed.data.seed, case: :lower)
    salt = Base.decode16!(crashed.data.salt, case: :lower)
    assert Base.encode16(:crypto.hash(:sha256, seed), case: :lower) == commitment
    assert Outcome.crash_from_seed(seed, salt, 300, 100_000_000) == crashed.data.crash_x10000

    seqs = stream |> journal() |> Enum.map(&hd/1)
    assert seqs == Enum.to_list(1..length(seqs))

    types = stream |> journal() |> Enum.map(&Enum.at(&1, 1))
    assert types == ~w(ROUND_CREATED ROUND_OPENED BETTING_CLOSED ROUND_LAUNCHED ROUND_CRASHED)

    # The next round's commitment is this round's revealed seed (hash chain).
    next = await("ROUND_OPEN")

    assert Base.encode16(
             :crypto.hash(:sha256, Base.decode16!(next.data.commitment, case: :lower)),
             case: :lower
           ) ==
             commitment or next.data.commitment != commitment
  end

  test "two panels: admitted bets, manual cash-out judged against the crash instant", %{
    stream: stream
  } do
    start(stream)
    private("s1")
    open = await("ROUND_OPEN")
    Coordinator.place_bet(stream, bet_cmd("s1", open.round_id, 0))
    Coordinator.place_bet(stream, bet_cmd("s1", open.round_id, 1))
    assert_receive {:lr_private, "BET_ACCEPTED", %{panel: 0, bet_id: bet0}}, 1_000
    assert_receive {:lr_private, "BET_ACCEPTED", %{panel: 1}}, 1_000

    # Same panel again is refused.
    Coordinator.place_bet(stream, bet_cmd("s1", open.round_id, 0))
    assert_receive {:lr_private, "BET_REJECTED", %{code: "PANEL_BUSY"}}, 1_000

    launched = await("ROCKET_LAUNCHED")
    {_, data} = state(stream)

    Coordinator.cash_out(stream, %{
      session_id: "s1",
      command_id: Ecto.UUID.generate(),
      bet_id: bet0,
      received_at: launched.data.launch_at
    })

    if data.round.crash > 10_000 do
      assert_receive {:lr_private, "CASHOUT_ACCEPTED",
                      %{bet_id: ^bet0, cashout_x10000: 10_000, payout: "500"}},
                     1_000
    else
      assert_receive {:lr_private, "CASHOUT_REJECTED", %{code: "ROUND_ENDED"}}, 1_000
    end

    # A cash-out stamped at (or after) the crash instant is always rejected.
    Coordinator.cash_out(stream, %{
      session_id: "s1",
      command_id: Ecto.UUID.generate(),
      bet_id: bet0,
      received_at: data.round.crash_at
    })

    assert_receive {:lr_private, "CASHOUT_REJECTED", %{}}, 1_000

    await("ROUND_CRASHED", 6_000)
    assert_receive {:lr_private, "BET_LOST", %{panel: 1}}, 1_000
    types = stream |> journal() |> Enum.map(&Enum.at(&1, 1))
    assert Enum.count(types, &(&1 == "BET_ADMITTED")) == 2
  end

  test "auto cash-out pays exactly the target when reached", %{stream: stream} do
    start(stream)
    private("s2")
    open = await("ROUND_OPEN")
    Coordinator.place_bet(stream, bet_cmd("s2", open.round_id, 0, %{auto: 10_100}))
    assert_receive {:lr_private, "BET_ACCEPTED", %{}}, 1_000
    await("ROCKET_LAUNCHED")
    {_, data} = state(stream)

    if data.round.crash >= 10_100 do
      assert_receive {:lr_private, "CASHOUT_ACCEPTED",
                      %{cashout_x10000: 10_100, trigger: "AUTO", payout: "505"}},
                     2_000
    else
      assert_receive {:lr_private, "BET_LOST", %{}}, 2_000
    end
  end

  test "a bet whose debit is not confirmed by launch is excluded", %{stream: stream} do
    PlatformStub.set_bet(fn body ->
      Process.sleep(600)
      PlatformStub.default_bet(body)
    end)

    start(stream)
    private("s3")
    open = await("ROUND_OPEN")
    Coordinator.place_bet(stream, bet_cmd("s3", open.round_id, 0))
    await("ROCKET_LAUNCHED")
    assert_receive {:lr_private, "BET_REJECTED", %{code: "LATE", refund: "PENDING"}}, 2_000
    types = stream |> journal() |> Enum.map(&Enum.at(&1, 1))
    assert "BET_EXCLUDED" in types
    refute "BET_ADMITTED" in types
  end

  test "bets after the cut-off are refused", %{stream: stream} do
    start(stream)
    private("s4")
    open = await("ROUND_OPEN")

    Coordinator.place_bet(
      stream,
      bet_cmd("s4", open.round_id, 0, %{received_at: open.data.close_at})
    )

    assert_receive {:lr_private, "BET_REJECTED", %{code: "BETTING_CLOSED"}}, 1_000
  end

  test "an interrupted round is voided on recovery", %{stream: stream} do
    start(stream)
    open = await("ROUND_OPEN")
    stop_supervised!({Coordinator, stream})
    # Let the old lease expire, then a new coordinator recovers.
    expire_lease(stream)
    start(stream)
    voided = await("ROUND_VOIDED")
    assert voided.round_id == open.round_id
    assert voided.data.reason == "COORDINATOR_FAILOVER"
    await("ROUND_OPEN")
  end

  test "a coordinator that lost its lease cannot write", %{stream: stream} do
    pid = start(stream)
    await("ROUND_OPEN")
    ref = Process.monitor(pid)
    # Another holder takes over (token increments).
    expire_lease(stream)
    {:ok, _} = Lease.acquire(stream, "intruder", 10_000)
    before = length(journal(stream))
    assert_receive {:DOWN, ^ref, :process, ^pid, reason}, 5_000
    assert reason in [:lease_lost, {:shutdown, :lease_lost}]
    assert length(journal(stream)) == before
  end

  test "curve table is loaded once and shared" do
    assert Curve.default() == Curve.default()
  end
end
