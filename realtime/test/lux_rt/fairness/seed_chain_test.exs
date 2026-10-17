defmodule LuxRt.Fairness.SeedChainTest do
  @moduledoc "Seed-chain ceremony, activation and rotation (doc 07 §6.1)."
  use LuxRt.DataCase, async: false

  alias LuxRt.Fairness.SeedChain
  alias LuxRt.Math.Outcome
  alias LuxRt.PlatformStub
  alias LuxRt.Repo
  alias LuxRt.Rounds.Coordinator
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
    Ecto.Adapters.SQL.Sandbox.mode(Repo, {:shared, self()})
    timing = Application.get_env(:lux_rt, :timing)
    fairness = Application.get_env(:lux_rt, :fairness)
    Application.put_env(:lux_rt, :timing, @timing)
    # Production behaviour: only ceremony chains are played.
    Application.put_env(:lux_rt, :fairness, Keyword.put(fairness, :auto_chain, false))

    on_exit(fn ->
      Application.put_env(:lux_rt, :timing, timing)
      Application.put_env(:lux_rt, :fairness, fairness)
    end)

    start_supervised!(PlatformStub)
    stream = "c#{System.unique_integer([:positive])}"
    LuxRtWeb.Endpoint.subscribe("stream:" <> stream)
    {:ok, stream: stream}
  end

  defp beacon do
    sig = :crypto.strong_rand_bytes(96)
    {Base.encode16(:crypto.hash(:sha256, sig), case: :lower), Base.encode16(sig, case: :lower)}
  end

  defp activation(facts, {randomness, signature}, overrides \\ %{}) do
    Map.merge(
      %{
        "chain_id" => facts.chain_id,
        "stream" => facts.stream,
        "drand_round" => facts.drand_round,
        "randomness" => randomness,
        "signature" => signature
      },
      overrides
    )
  end

  defp status(chain_id) do
    %{rows: [[status, salt, source]]} =
      Repo.query!(
        "SELECT status, salt, salt_source FROM rt.seed_chain WHERE chain_id = $1::text::uuid",
        [chain_id]
      )

    {status, salt, source}
  end

  defp committed_and_active(stream) do
    {:ok, facts} = SeedChain.commit(stream, delay_s: 60)
    b = beacon()
    :ok = SeedChain.activate(activation(facts, b))
    {facts, b}
  end

  defp await(event, timeout \\ 6_000) do
    assert_receive %Broadcast{event: ^event, payload: payload}, timeout
    payload
  end

  defp created(stream) do
    %{rows: rows} =
      Repo.query!(
        "SELECT payload FROM rt.round_journal WHERE stream_id = $1 AND type = 'ROUND_CREATED' ORDER BY stream_seq",
        [stream]
      )

    List.flatten(rows)
  end

  test "the ceremony commits to a future drand round and keeps the salt open", %{stream: s} do
    now = 1_800_000_000
    assert {:error, _} = SeedChain.commit(s, delay_s: 10, now: now)
    {:ok, facts} = SeedChain.commit(s, delay_s: 3_600, now: now)

    assert facts.drand_round_time >= now + 3_600
    assert facts.drand_round_time - (now + 3_600) < 3
    assert {"COMMITTED", "", "drand-pending"} = status(facts.chain_id)
    assert byte_size(facts.terminal_hash) == 64
    # Not playable yet.
    assert SeedChain.active(s) == nil
  end

  test "activation checks the beacon, round and state, and retires the old chain", %{stream: s} do
    {first, _} = committed_and_active(s)
    {:ok, facts} = SeedChain.commit(s, delay_s: 60)
    {randomness, signature} = b = beacon()

    assert {:error, :bad_beacon} =
             SeedChain.activate(
               activation(facts, b, %{"randomness" => String.duplicate("0", 64)})
             )

    assert {:error, :wrong_round} =
             SeedChain.activate(activation(facts, b, %{"drand_round" => facts.drand_round + 1}))

    assert {:error, :wrong_stream} = SeedChain.activate(activation(facts, b, %{"stream" => "x"}))
    assert {:error, :malformed} = SeedChain.activate(%{"chain_id" => facts.chain_id})

    assert :ok = SeedChain.activate(activation(facts, b))
    # Idempotent redelivery.
    assert :ok = SeedChain.activate(activation(facts, b))

    {"ACTIVE", ^randomness, source} = status(facts.chain_id)

    assert source ==
             "drand:#{Application.fetch_env!(:lux_rt, :drand)[:chain_hash]}:#{facts.drand_round}"

    assert {"RETIRED", _, _} = status(first.chain_id)
    assert SeedChain.active_id(s) == facts.chain_id

    %{rows: [[stored]]} =
      Repo.query!(
        "SELECT drand_signature FROM rt.seed_chain WHERE chain_id = $1::text::uuid",
        [facts.chain_id]
      )

    assert stored == signature
    # A retired chain can never come back.
    assert {:error, :invalid_state} = SeedChain.activate(activation(first, beacon()))
  end

  test "without an active chain the stream waits; activation starts it", %{stream: s} do
    start_supervised!({Coordinator, s}, restart: :temporary)
    refute_receive %Broadcast{event: "ROUND_OPEN"}, 600

    {:ok, facts} = SeedChain.commit(s, delay_s: 60)
    {randomness, _} = b = beacon()
    :ok = SeedChain.activate(activation(facts, b))

    await("ROUND_OPEN", 8_000)
    crashed = await("ROUND_CRASHED")
    assert crashed.data.salt == randomness
    assert crashed.data.chain_id == facts.chain_id
    assert crashed.data.chain_index == 1

    seed = Base.decode16!(crashed.data.seed, case: :lower)
    salt = Base.decode16!(randomness, case: :lower)
    assert Outcome.crash_from_seed(seed, salt, 300, 100_000_000) == crashed.data.crash_x10000
  end

  test "a chain activated mid-round is adopted at the next round boundary", %{stream: s} do
    {a, {salt_a, _}} = committed_and_active(s)
    start_supervised!({Coordinator, s}, restart: :temporary)
    await("ROUND_OPEN")

    {:ok, b} = SeedChain.commit(s, delay_s: 60)
    {salt_b, _} = beacon_b = beacon()
    :ok = SeedChain.activate(activation(b, beacon_b))

    # The round in flight finishes on the chain (and salt) it was committed under.
    assert %{data: %{salt: ^salt_a}} = await("ROUND_CRASHED")
    await("ROUND_OPEN")
    assert %{data: %{salt: ^salt_b, chain_index: 1}} = await("ROUND_CRASHED")

    [first, second | _] = created(s)
    assert first["chain_id"] == a.chain_id
    assert second["chain_id"] == b.chain_id and second["chain_index"] == 1
  end

  test "an exhausted chain halts the stream", %{stream: s} do
    fairness = Application.get_env(:lux_rt, :fairness)
    Application.put_env(:lux_rt, :fairness, Keyword.put(fairness, :chain_length, 2))
    {facts, _} = committed_and_active(s)
    Application.put_env(:lux_rt, :fairness, fairness)

    start_supervised!({Coordinator, s}, restart: :temporary)

    for _ <- 1..2 do
      await("ROUND_OPEN")
      await("ROUND_CRASHED")
    end

    refute_receive %Broadcast{event: "ROUND_OPEN"}, 800

    assert {"EXHAUSTED", _, _} = status(facts.chain_id)
    assert length(created(s)) == 2
  end
end
